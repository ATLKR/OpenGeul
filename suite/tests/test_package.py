"""Corresponding source archives must identify the exact clean build input."""
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[2]


def implementation():
    path = ROOT/'suite/package.py'
    assert path.is_file(), 'Suite source packaging implementation is required'
    spec = importlib.util.spec_from_file_location('suite_package_under_test', path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


class PackageSourceTests(unittest.TestCase):
    def repository(self, path):
        subprocess.run(['git','init','-q',str(path)],check=True)
        subprocess.run(['git','-C',str(path),'config','user.name','Suite test'],check=True)
        subprocess.run(['git','-C',str(path),'config','user.email','suite-test@example.invalid'],check=True)
        (path/'LICENSE').write_text('preserved source license')
        subprocess.run(['git','-C',str(path),'add','LICENSE'],check=True)
        subprocess.run(['git','-C',str(path),'commit','-qm','test source'],check=True)

    def test_clean_commit_is_archived_with_its_original_license(self):
        module = implementation()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)/'repo'; self.repository(root)
            target = Path(folder)/'source.zip'
            commit = module.write_source_archive(root,target)
            self.assertEqual(len(commit),40)
            with zipfile.ZipFile(target) as archive:
                self.assertEqual(archive.read('LICENSE'),b'preserved source license')

    def test_dirty_build_source_cannot_claim_the_clean_commit(self):
        module = implementation()
        for dirty in ('tracked','untracked'):
            with self.subTest(dirty=dirty),tempfile.TemporaryDirectory() as folder:
                root=Path(folder)/'repo'; self.repository(root)
                (root/('LICENSE' if dirty=='tracked' else 'new-source.py')).write_text('uncommitted')
                target=Path(folder)/'source.zip'
                with self.assertRaises(ValueError): module.write_source_archive(root,target)
                self.assertFalse(target.exists())

    def test_source_archive_never_overwrites_an_existing_file(self):
        module=implementation()
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)/'repo'; self.repository(root)
            target=Path(folder)/'source.zip'; target.write_bytes(b'keep')
            with self.assertRaises(ValueError): module.write_source_archive(root,target)
            self.assertEqual(target.read_bytes(),b'keep')

    def test_assembly_inventory_uses_the_authenticated_lock_architecture(self):
        from suite import prepare
        for architecture in ('x64', 'arm64'):
            with self.subTest(architecture=architecture), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)/'repo'; self.repository(root)
                config = root/'suite/config'; config.mkdir(parents=True)
                (config/'product.json').write_text(json.dumps({'version': 'test-version'}))
                (root/'suite/worker').mkdir(); (root/'suite/worker/office_worker.py').write_text('# worker')
                (root/'suite/notices').mkdir(); (root/'suite/notices/upstream.txt').write_text('upstream notices')
                subprocess.run(['git', '-C', str(root), 'add', 'suite'], check=True)
                subprocess.run(['git', '-C', str(root), 'commit', '-qm', 'package fixture'], check=True)
                runtime = Path(folder)/'runtime'; runtime.mkdir(); (runtime/'LICENSE').write_text('runtime license')
                shell = Path(folder)/'shell'; shell.mkdir(); (shell/'OpenGeul.Office.exe').write_bytes(b'shell')
                hwp = Path(folder)/'hwp.zip'
                with zipfile.ZipFile(hwp, 'w') as archive: archive.writestr('OpenGeul.exe', b'hwp editor')
                lock = {'architecture': architecture, 'version': 'test-version',
                        'runtime': {'version': 'upstream-version', 'sourceUrl': 'https://example.org/source',
                                    'sourceSha256': 'a'*64},
                        'hwp': {'size': hwp.stat().st_size, 'sha256': prepare.sha256(hwp),
                                'sourceUrl': 'https://example.org/hwp-source',
                                'provenanceUrl': 'https://example.org/hwp-provenance'}}
                def brand(source, destination, product):
                    shutil.copytree(source, destination)
                    return {'schemaVersion': 1}
                # The inventory validator is an independently tested boundary;
                # preserve its x64 default so missing ARM64 forwarding is observable.
                def inventory(path, *, architecture='x64'):
                    return {'schemaVersion': 1, 'architecture': architecture, 'files': {}}
                output = Path(folder)/'output'
                module = implementation()
                with patch.object(module, 'ROOT', root), patch.dict('sys.modules', {
                        'prepare': prepare, 'runtime_branding': SimpleNamespace(brand_runtime=brand),
                        'payload': SimpleNamespace(create_inventory=inventory, verify_payload=lambda *args: None)}):
                    module.assemble(runtime=runtime, hwp=hwp, shell=shell, output=output, lock=lock)
                self.assertEqual(architecture, json.loads((output/'suite-provenance.json').read_text())['architecture'])
                self.assertEqual(architecture, json.loads((output/'suite-inventory.json').read_text())['architecture'])


if __name__ == '__main__': unittest.main()
