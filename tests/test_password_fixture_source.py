"""Execute the generator's real pre-import trust boundary with synthetic artifacts.

This portable source test makes no document/API/UI claim. The full generator
must additionally run against the pinned real WASM and independent CFB/XML oracle.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
FILES = ('rhwp.js', 'rhwp_bg.wasm', 'rhwp.d.ts', 'rhwp_bg.wasm.d.ts', 'package.json', 'LICENSE')
GENERATOR = 'wasm-pack 0.14.0 --target web --release --no-opt --no-default-features --features console_error_panic_hook,wasm-api'
BOUNDARY = '// Independently confirm that the prior document is our known smoke fixture.'


class PasswordFixtureSourceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.vendor = self.root / 'vendor'
        self.vendor.mkdir()
        self.node = shutil.which('node')
        self.assertIsNotNone(self.node, 'Node from the declared build toolchain is required')
        source = (ROOT / 'e2e/password/generate-password-fixtures.mjs').read_text(encoding='utf-8')
        self.assertEqual(source.count(BOUNDARY), 1)
        self.program = self.root / 'source-boundary.mjs'
        self.program.write_text(source.split(BOUNDARY)[0] +
                                '\nconsole.log(JSON.stringify({qualification}));\n', encoding='utf-8')
        for name, data in (
            ('config/upstream.lock.json', (ROOT / 'config/upstream.lock.json').read_bytes()),
            ('overlay/hwpx_namespaces.rs', b'owned namespace helper'),
            ('scripts/patch_namespaces.py', b'owned namespace patcher'),
        ):
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        for name in FILES:
            (self.vendor / name).write_bytes(b'owned synthetic artifact')
        (self.vendor / 'rhwp_bg.wasm').write_bytes(b'\0asm\1\0\0\0')
        self.package_version('0.9.0')

    def package_version(self, version):
        (self.vendor / 'package.json').write_text(json.dumps({'version': version}))

    def sha(self, path):
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def proof(self, rebuilt):
        hashes = {name: self.sha(self.vendor / name) for name in FILES}
        if rebuilt:
            value = {
                'upstream': json.loads((self.root / 'config/upstream.lock.json').read_text()),
                'namespaceHelper': self.sha(self.root / 'overlay/hwpx_namespaces.rs'),
                'namespacePatcher': self.sha(self.root / 'scripts/patch_namespaces.py'),
                'artifacts': hashes,
                'generator': GENERATOR,
            }
            name = 'OPEN_GEUL_WASM.json'
        else:
            value = {'version': '0.9.0', 'commit': 'c9095c5f67632e6721e800ccc7fb43ea49d26682',
                     'artifacts': {key: {'sha256': sha} for key, sha in hashes.items()}}
            name = 'PROVENANCE.json'
        (self.vendor / name).write_text(json.dumps(value))
        return self.vendor / name, value

    def run_boundary(self):
        env = {'PATH': str(Path(self.node).parent) + os.pathsep + os.defpath,
               'LANG': 'C.UTF-8', 'HOME': str(self.root),
               'XDG_CACHE_HOME': str(self.root / 'cache')}
        if os.name == 'nt':
            env['SystemRoot'] = os.environ.get('SystemRoot', r'C:\Windows')
        result = subprocess.run([self.node, str(self.program), str(self.vendor),
                                 str(self.root / 'prior'), str(self.root / 'output')],
                                cwd=self.root, env=env, stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=15)
        return result.returncode, result.stdout

    def require_rejected(self):
        code, output = self.run_boundary()
        self.assertNotEqual(code, 0, 'Invalid source profile must reject before document generation')
        self.assertEqual(output, b'', 'Rejected source profiles must not report qualification')
        self.assertFalse((self.root / 'output').exists())

    def test_current_pinned_vendor_remains_preliminary(self):
        self.proof(False)
        code, output = self.run_boundary()
        self.assertEqual(code, 0, 'Current pinned vendor must reach the independent document boundary')
        self.assertEqual(json.loads(output), {'qualification': 'preliminary-pinned-vendor'})

    def test_current_exact_rebuild_reaches_final_source_boundary(self):
        self.proof(True)
        code, output = self.run_boundary()
        self.assertEqual(code, 0, 'Current exact rebuild must reach the independent document boundary')
        self.assertEqual(json.loads(output), {'qualification': 'final-source-bound'})

    def test_other_package_versions_cannot_reuse_a_valid_source_proof(self):
        for version in ('0.8.7', '0.9.1', '1.0.0'):
            with self.subTest(version=version):
                self.package_version(version)
                self.proof(True)
                self.require_rejected()

    def test_vendor_version_and_commit_are_both_exact(self):
        path, value = self.proof(False)
        for key, wrong in (('version', '0.8.7'), ('commit', '1a76570e833917d15817415a53c09ad61ab3203f')):
            with self.subTest(field=key):
                changed = dict(value, **{key: wrong})
                path.write_text(json.dumps(changed))
                self.require_rejected()

    def test_even_matching_proof_cannot_authorize_an_unreviewed_source_lock(self):
        path = self.root / 'config/upstream.lock.json'
        original = json.loads(path.read_text())
        for project in ('hop', 'rhwp'):
            for key, wrong in (('version', '99.0.0'), ('commit', '0' * 40)):
                with self.subTest(project=project, field=key):
                    changed = json.loads(json.dumps(original))
                    changed[project][key] = wrong
                    path.write_text(json.dumps(changed))
                    self.proof(True)
                    self.require_rejected()
        path.write_text(json.dumps(original))

    def test_each_artifact_hash_remains_mandatory_for_both_profiles(self):
        for rebuilt in (False, True):
            for name in FILES:
                with self.subTest(rebuilt=rebuilt, artifact=name):
                    for marker in ('OPEN_GEUL_WASM.json', 'PROVENANCE.json'):
                        (self.vendor / marker).unlink(missing_ok=True)
                    path = self.vendor / name
                    original = path.read_bytes()
                    self.proof(rebuilt)
                    path.write_bytes(original + b'changed')
                    self.require_rejected()
                    path.write_bytes(original)

    def test_rebuild_lock_and_namespace_bytes_are_not_advisory(self):
        proof, value = self.proof(True)
        mutations = ('upstream', 'namespaceHelper', 'namespacePatcher')
        for key in mutations:
            with self.subTest(field=key):
                changed = json.loads(json.dumps(value))
                changed[key] = {} if key == 'upstream' else '0' * 64
                proof.write_text(json.dumps(changed))
                self.require_rejected()

    def test_rebuild_command_is_exact_and_required(self):
        proof, value = self.proof(True)
        for command in (None, GENERATOR.replace(' --no-default-features --features console_error_panic_hook,wasm-api', ''),
                        GENERATOR.replace('--target web', '--target nodejs')):
            with self.subTest(commandPresent=command is not None):
                changed = dict(value)
                if command is None:
                    del changed['generator']
                else:
                    changed['generator'] = command
                proof.write_text(json.dumps(changed))
                self.require_rejected()

    def test_missing_provenance_cannot_become_preliminary(self):
        self.require_rejected()


if __name__ == '__main__':
    unittest.main()
