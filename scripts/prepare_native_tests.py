"""Register downstream integration targets when upstream disables auto-discovery."""
from pathlib import Path
import argparse
import hashlib
import json
import tomllib

ROOT = Path(__file__).resolve().parents[1]
TARGETS = {
    'opengeul_table_height': 'table_height_test.rs',
    'opengeul_pdf_policy': 'opengeul_pdf_policy_tests.rs',
}


def prepare(core: Path) -> None:
    manifest = core/'Cargo.toml'
    original = manifest.read_text(encoding='utf-8')
    names = {item['name'] for item in tomllib.loads(original).get('test', [])}
    paths = {name: core/f'tests/{name}.rs' for name in TARGETS}
    if names.intersection(TARGETS) or any(path.exists() for path in paths.values()):
        raise ValueError('Refusing to replace an existing upstream integration target')
    texts = {name: (ROOT/'overlay'/filename).read_bytes() for name, filename in TARGETS.items()}
    rendered = original + '\n# OpenGeul distribution-only integration gates.\n'
    for name in TARGETS:
        rendered += f'\n[[test]]\nname = "{name}"\npath = "tests/{name}.rs"\n'
        if name == 'opengeul_pdf_policy':
            rendered += 'required-features = ["native-skia"]\n'
    paths[next(iter(TARGETS))].parent.mkdir(exist_ok=True)
    for name, path in paths.items():
        path.write_bytes(texts[name])
    manifest.write_text(rendered, encoding='utf-8')
    (core/'.opengeul-native-tests.json').write_text(json.dumps({
        'targets': {name: hashlib.sha256(texts[name]).hexdigest() for name in TARGETS},
        'originalManifestSha256': hashlib.sha256(original.encode()).hexdigest(),
    }, indent=2)+'\n', encoding='utf-8')
    print('Registered native table geometry and PDF embedding-policy integration gates.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('core', type=Path)
    prepare(parser.parse_args().core.resolve())
