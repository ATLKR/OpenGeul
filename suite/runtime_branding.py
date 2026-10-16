"""Brand a verified, extracted Office runtime without touching its input or PE files.

Input archive authentication and GUI qualification belong to the package builder.
This module edits only configuration, UI XML and original OpenGeul artwork.
"""
from __future__ import annotations

import argparse
import configparser
import hashlib
import json
from pathlib import Path
import re
import shutil
import xml.etree.ElementTree as ET
from xml.sax.saxutils import quoteattr
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parent
ASSETS = ROOT / 'branding'
OOR = '{http://openoffice.org/2001/registry}'
SERVICES = {
    'com.sun.star.text.TextDocument': 'writer',
    'com.sun.star.text.GlobalDocument': 'writer',
    'com.sun.star.text.WebDocument': 'writer',
    'com.sun.star.sheet.SpreadsheetDocument': 'calc',
    'com.sun.star.presentation.PresentationDocument': 'impress',
    'com.sun.star.drawing.DrawingDocument': 'draw',
    'com.sun.star.formula.FormulaProperties': 'math',
    'com.sun.star.sdb.OfficeDatabaseDocument': 'base',
}
START_BUTTONS = {'writer_all': 'writer', 'calc_all': 'calc', 'impress_all': 'impress',
                 'draw_all': 'draw', 'math_all': 'math', 'database_all': 'base'}
MODULES = {'hwp', 'writer', 'calc', 'impress', 'draw', 'math', 'base'}
BRAND_IMAGES = ('intro.png', 'intro-highres.png', 'logo.svg', 'logo_inverted.svg',
                'logo-sc.svg', 'logo-sc_inverted.svg', 'about.svg', 'donate1.png', 'donate2.png')
for prefix, uri in [('oor', OOR[1:-1]), ('xs', 'http://www.w3.org/2001/XMLSchema'),
                    ('xsi', 'http://www.w3.org/2001/XMLSchema-instance'),
                    ('install', 'http://openoffice.org/2004/installation')]:
    ET.register_namespace(prefix, uri)


def sha256(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def _hashes(root: Path) -> dict[str, str]:
    return {path.relative_to(root).as_posix(): sha256(path)
            for path in sorted(root.rglob('*')) if path.is_file()}


def _canonical(value: dict) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')


def _read_ini(path: Path) -> configparser.RawConfigParser:
    config = configparser.RawConfigParser()
    config.optionxform = str
    config.read_string(path.read_text(encoding='utf-8-sig'))
    return config


def _write_ini(path: Path, config: configparser.RawConfigParser) -> None:
    with path.open('w', encoding='utf-8', newline='\n') as stream:
        config.write(stream, space_around_delimiters=False)


def _validate_manifest(manifest: dict) -> None:
    if manifest.get('schemaVersion') != 1 or manifest.get('productName') != 'OpenGeul Office':
        raise ValueError('Expected the OpenGeul Office schemaVersion 1 manifest')
    if manifest.get('vendor') != 'ATLKR' or set(manifest.get('modules', {})) != MODULES:
        raise ValueError('The Suite vendor or seven-module manifest is incomplete')
    profile = manifest.get('runtime', {}).get('profileDirectory', '')
    if not re.fullmatch(r'OpenGeul/[A-Za-z0-9_-]+/[0-9]+', profile):
        raise ValueError('The runtime must use an isolated OpenGeul profile directory')
    extensions = set()
    for name, module in manifest['modules'].items():
        if module.get('displayName') != 'OpenGeul ' + ('HWP' if name == 'hwp' else name.title()):
            raise ValueError('Unexpected Suite module display name: ' + name)
        formats = module.get('extensions')
        if not isinstance(formats, list) or not formats or len(formats) != len(set(formats)):
            raise ValueError('Missing or repeated format extensions: ' + name)
        if any(not isinstance(ext, str) or not re.fullmatch('[a-z0-9]+', ext) for ext in formats):
            raise ValueError('Invalid format extension: ' + name)
        if extensions.intersection(formats):
            raise ValueError('A format cannot route to two Suite engines')
        extensions.update(formats)
        if name == 'hwp':
            if module.get('factory') is not None or module.get('filters') != {}:
                raise ValueError('HWP/HWPX must stay on the existing OpenGeul engine')
        elif not str(module.get('factory', '')).startswith('private:factory/') or \
                set(module.get('filters', {})) != set(formats):
            raise ValueError('Missing explicit factory or save filters: ' + name)
    for name in BRAND_IMAGES:
        if not (ASSETS / name).is_file():
            raise ValueError('Missing OpenGeul branding artwork: ' + name)


def _component(root: ET.Element, package: str, name: str):
    return (node for node in root.iter(OOR + 'component-data')
            if node.get(OOR + 'package') == package and node.get(OOR + 'name') == name)


def _child(node: ET.Element, tag: str, name: str):
    return next((child for child in node.findall(tag) if child.get(OOR + 'name') == name), None)


def _value(node: ET.Element, name: str, text: str) -> bool:
    prop = _child(node, 'prop', name)
    if prop is None:
        return False
    changed = False
    for value in prop.findall('value'):
        if value.text != text:
            value.text = text
            changed = True
    return changed


def _xml(path: Path) -> ET.ElementTree:
    return ET.parse(path, parser=ET.XMLParser(target=ET.TreeBuilder(insert_comments=True)))


def _write_xml(path: Path, tree: ET.ElementTree) -> None:
    # ElementTree drops namespace declarations used only in attribute *values*,
    # e.g. oor:type="xs:string". LibreOffice's registry resolves that QName and
    # cannot initialize if its xs binding disappears during serialization.
    namespaces = []
    with path.open('rb') as stream:
        for event, value in ET.iterparse(stream, events=('start-ns', 'start')):
            if event == 'start':
                break
            namespaces.append(value)
    data = ET.tostring(tree.getroot(), encoding='unicode')
    end = data.index('>')
    opening = data[:end]
    for prefix, uri in namespaces:
        name = 'xmlns:' + prefix if prefix else 'xmlns'
        if not re.search(r'\s' + re.escape(name) + r'=', opening):
            opening += ' ' + name + '=' + quoteattr(uri)
    path.write_text('<?xml version="1.0" encoding="utf-8"?>\n' + opening + data[end:], encoding='utf-8')


def _brand_registry(runtime: Path, manifest: dict) -> None:
    product_found = False
    modules_found = set()
    for path in sorted((runtime / 'share/registry').rglob('*')):
        if path.suffix not in ('.xcd', '.xcu'):
            continue
        tree = _xml(path)
        changed = False
        for component in _component(tree.getroot(), 'org.openoffice', 'Setup'):
            product = _child(component, 'node', 'Product')
            if product is not None and _child(product, 'prop', 'ooName') is not None:
                product_found = True
                changed |= _value(product, 'ooName', manifest['productName'])
            for factory in component.iter('node'):
                service = factory.get(OOR + 'name', '')
                module = SERVICES.get(service)
                if module is None and service.startswith(('com.sun.star.sdb.', 'com.sun.star.report.')):
                    module = 'base'
                if module is None:
                    continue
                prop = _child(factory, 'prop', 'ooSetupFactoryUIName')
                if prop is None:
                    continue
                modules_found.add(module)
                for value in prop.findall('value'):
                    label = manifest['modules'][module]['displayName']
                    if value.text and value.text.startswith('Base:'):
                        label += value.text[len('Base'):]
                    if service == 'com.sun.star.text.WebDocument':
                        label += '/Web'
                    if value.text != label:
                        value.text = label
                        changed = True
        for component in _component(tree.getroot(), 'org.openoffice.Office.UI', 'ToolbarMode'):
            applications = _child(component, 'node', 'Applications')
            if applications is not None:
                for name in ('Writer', 'Calc', 'Impress', 'Draw'):
                    application = _child(applications, 'node', name)
                    if application is not None:
                        changed |= _value(application, 'Active', 'Tabbed')
                        changed |= _value(component, 'Active' + name, 'notebookbar.ui')
        if changed:
            _write_xml(path, tree)
    if not product_found or modules_found != MODULES - {'hwp'}:
        raise ValueError('Runtime product or six Office factory registrations were not recognized')


def _brand_text(text: str, manifest: dict) -> str:
    # Copyright, attribution and licensing text are deliberately retained.
    if re.search(r'copyright|licens|contributor|derived from|based on', text, re.I):
        return text
    for module in MODULES - {'hwp'}:
        label = module.title()
        text = re.sub(r'(?:%PRODUCTNAME|LibreOffice(?:Dev)?)\s+' + label + r'\b',
                      manifest['modules'][module]['displayName'], text)
    return re.sub(r'\bLibreOffice(?:Dev)?\b', manifest['productName'], text)


def _brand_ui(runtime: Path, manifest: dict) -> None:
    for path in sorted((runtime / 'share/config').rglob('*.ui')):
        tree = _xml(path)
        changed = False
        for node in tree.iter():
            if node.get('translatable') == 'yes' and node.text:
                label = _brand_text(node.text, manifest)
                if label != node.text:
                    node.text = label
                    changed = True
        if path.name == 'startcenter.ui':
            for obj in tree.iter('object'):
                module = START_BUTTONS.get(obj.get('id'))
                if module:
                    for prop in obj.findall('property'):
                        if prop.get('name') == 'label':
                            prop.text = manifest['modules'][module]['displayName']
                            changed = True
        if changed:
            _write_xml(path, tree)


def _brand_images(runtime: Path) -> None:
    for name in BRAND_IMAGES:
        target = runtime / 'program' / (name if name.startswith('intro') else 'shell/' + name)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ASSETS / name, target)
    # Keep command artwork and every unrelated member byte-identical. These are
    # the application/document icons shown by the existing native Start Center.
    icons = {f'res/{name}_32_8.png': ASSETS / 'icon-32.png'
             for name in ('odt', 'ods', 'odp', 'odg', 'odf', 'odb')}
    icons.update({f'res/{name}128.png': ASSETS / 'icon-128.png'
                  for name in ('writer', 'calc', 'impress', 'draw', 'math', 'base')})
    for path in sorted((runtime / 'share/config').glob('images*.zip')):
        with ZipFile(path) as source:
            members = source.infolist()
            if len({entry.filename for entry in members}) != len(members):
                raise ValueError('Duplicate image archive member: ' + path.name)
            if not any(entry.filename in icons for entry in members):
                continue
            temporary = path.with_suffix('.opengeul-tmp')
            with ZipFile(temporary, 'w') as destination:
                destination.comment = source.comment
                for entry in members:
                    artwork = icons.get(entry.filename)
                    destination.writestr(entry, artwork.read_bytes() if artwork else source.read(entry))
        temporary.replace(path)


def brand_runtime(source: Path, destination: Path, manifest: dict) -> dict:
    """Copy into an absent destination; return/write a portable branding receipt.

    Legal notices and executables are never rewritten. A failed operation removes
    only its own newly-created output. The caller authenticates the input archive.
    """
    source, destination = Path(source), Path(destination)
    if destination.exists() or destination.is_symlink():
        raise FileExistsError('Branding output already exists: ' + str(destination))
    if source.is_symlink() or not source.is_dir():
        raise ValueError('Expected an extracted runtime directory, not a link')
    source = source.resolve()
    destination = destination.resolve()
    if source == destination or source in destination.parents or destination in source.parents:
        raise ValueError('Source and branding output must be separate directories')
    _validate_manifest(manifest)
    for path in source.rglob('*'):
        if path.is_symlink() or (hasattr(path, 'is_junction') and path.is_junction()) or \
                not (path.is_file() or path.is_dir()):
            raise ValueError('Runtime links or special files are not accepted: ' + str(path))
    original = _hashes(source)
    root_legal = {path.name.lower() for path in source.iterdir()
                  if path.is_file() and path.stat().st_size}
    if not root_legal.intersection(('license', 'license.txt', 'license.html')) or \
            not root_legal.intersection(('notice', 'notice.txt')):
        raise ValueError('The runtime must contain its original license and NOTICE files')
    if 'opengeul-branding.json' in original:
        raise ValueError('Expected an unmodified upstream runtime input')
    bootstrap_name = next((name for name in ('program/bootstrap.ini', 'program/bootstraprc') if name in original), None)
    version_name = next((name for name in ('program/version.ini', 'program/versionrc') if name in original), None)
    if not bootstrap_name or not version_name:
        raise ValueError('Runtime bootstrap/version metadata is missing')
    bootstrap, version = _read_ini(source / bootstrap_name), _read_ini(source / version_name)
    build_id = version.get('Version', 'buildid', fallback='')
    if not re.fullmatch('[a-fA-F0-9]{40}', build_id):
        raise ValueError('Runtime buildid must identify its immutable corresponding source')
    source_metadata = {'buildId': build_id, 'productKey': bootstrap.get('Bootstrap', 'ProductKey', fallback=''),
                       'sourceUrl': 'https://github.com/LibreOffice/core/tree/' + build_id}
    legal = {name: digest for name, digest in original.items()
             if re.match(r'^(LICENSE|NOTICE|COPYING|COPYRIGHT|CREDITS)(?:[._-]|$)', Path(name).name, re.I)}
    # Exclusive directory creation also protects an existing empty output.
    destination.mkdir(parents=True, exist_ok=False)
    try:
        shutil.copytree(source, destination, dirs_exist_ok=True)
        bootstrap.set('Bootstrap', 'ProductKey', manifest['productName'])
        bootstrap.set('Bootstrap', 'UserInstallation', '$SYSUSERCONFIG/' + manifest['runtime']['profileDirectory'])
        _write_ini(destination / bootstrap_name, bootstrap)
        version.set('Version', 'Vendor', manifest['vendor'])
        version.set('Version', 'UpdateURL', '')
        version.set('Version', 'ExtensionUpdateURL', '')
        version.set('Version', 'UpdateID', 'OpenGeul_Office')
        _write_ini(destination / version_name, version)
        _brand_registry(destination, manifest)
        _brand_ui(destination, manifest)
        _brand_images(destination)
        (destination / 'opengeul-product.json').write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        (destination / 'OPENGEUL_SOURCE_NOTICE.txt').write_text(
            'OpenGeul Office runtime configuration and artwork modifications\n'
            'Upstream corresponding source: ' + source_metadata['sourceUrl'] + '\n'
            'OpenGeul changes: https://github.com/ATLKR/OpenGeul/tree/work/opengeul-office-suite/suite\n'
            'The package source bundle must include these changes and its exact OpenGeul commit.\n'
            'Original LICENSE, NOTICE and source notices retain their original terms.\n'
            'Configuration and image changes do not re-sign or rename executable PE resources.\n', encoding='utf-8')
        after = _hashes(destination)
        if any(after.get(name) != digest for name, digest in legal.items()):
            raise ValueError('A preserved legal notice was unexpectedly changed')
        receipt = {'schemaVersion': 1, 'productName': manifest['productName'],
                   'manifestSha256': hashlib.sha256(_canonical(manifest)).hexdigest(),
                   'source': source_metadata,
                   'inputTreeSha256': hashlib.sha256(_canonical(original)).hexdigest(),
                   'modifiedFiles': {name: {'beforeSha256': original.get(name), 'sha256': digest}
                                     for name, digest in after.items() if original.get(name) != digest},
                   'preservedLegalFiles': legal}
        (destination / 'opengeul-branding.json').write_text(
            json.dumps(receipt, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        return receipt
    except BaseException:
        shutil.rmtree(destination)
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('destination', type=Path)
    parser.add_argument('--manifest', type=Path, default=ROOT / 'config/product.json')
    args = parser.parse_args()
    receipt = brand_runtime(args.source, args.destination, json.loads(args.manifest.read_text(encoding='utf-8')))
    print(json.dumps(receipt, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
