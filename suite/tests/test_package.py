"""Corresponding source archives must identify the exact clean build input."""
import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest
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


if __name__ == '__main__': unittest.main()
