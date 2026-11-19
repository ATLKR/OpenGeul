"""COM pins and original graphs survive only the reviewed rhwp 0.9.1 delta."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import tomllib
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
import native_activation

REGISTRY = 'registry+https://github.com/rust-lang/crates.io-index'
ORIGINAL_CLI_IDENTITIES = 'd06b23f4ee1dfe173aedbe954fdf35abafd39d4321b1507da0cee1bb7e9d32ac'
ORIGINAL_DESKTOP_IDENTITIES = '6a0461d5ba6d87f11162c3a27437bb2468f9197b658c0b12edba2b54420898a6'
ORIGINAL_CLI_EDGES = '85980c95458587c00c022bf3005078694610bb279aaf9d344428f7a1562cb96b'
ORIGINAL_DESKTOP_EDGES = '87171be0ccf5771bf53211fd1ac45b9f62e33f8a87eec9f30d0a2bca981fa662'
ORIGINAL_RHWP_EDGES = {
    'desktop-cargo.lock.toml': '26a5efebbae3523dab5b3ae201035271b1081925ad5813faee984bd15baad9f7',
    'cli-cargo.lock.toml': 'cc9bff5bfb52a6faecf2447cde496f84c4e4f467c5399538d33be9fda317d98b',
}
NEW_WINDOWS = {
    ('windows', '0.61.3'): '9babd3a767a4c1aef6900409f85f5d53ce2544ccdfaa86dad48c91782c6d6893',
    ('windows-collections', '0.2.0'): '3beeceb5e5cfd9eb1d76b381630e82c4241ccd0d27f1a39ed41b2760b255c5e8',
    ('windows-core', '0.61.2'): 'c0fdd3ddb90610c7638aa2b3a3ab2904fb9e5cdbecc643ddb3647212781c4ae3',
    ('windows-future', '0.2.1'): 'fc6a41e98427b19fe4b73c550f060b59fa592d7d686537eebf9385621bfbad8e',
    ('windows-link', '0.1.3'): '5e6ad25900d524eaabdbbb96d20b4311e1e7ae1699af4fb28c17ae66c80d798a',
    ('windows-numerics', '0.2.0'): '9150af68066c4c5c07ddc0ce30421554771e528bde427614c61038bc2c92c2b1',
    ('windows-result', '0.3.4'): '56f42bd332cc6c8eac5af113fc0c1fd6a8fd2aa08a0119358686e5160d0586c6',
    ('windows-strings', '0.4.2'): '56e6c93f3a0c3b36176cb1327a4958a0353d5d166c2a35cb268ace15e91d3b57',
    ('windows-threading', '0.1.0'): 'b66463ad2e0ea3bbf808b7f1d371311c80e115c0b71d60efc142cafbcfb057a6',
}
RHWP091_UPDATES = {
    'cfb':'0.16.0', 'read-fonts':'0.47.0', 'rhwp':'0.9.1',
    'rhwp-codec-resource':'0.1.1', 'rhwp-ooxml-chart':'0.1.1',
    'skera':'0.10.0', 'skrifa':'0.50.0', 'write-fonts':'0.56.0',
}
CLI_NATIVE_UPDATES = {
    'rhwp-hayro-ccitt':'0.3.0-rhwp.2', 'rhwp-hayro-jbig2':'0.3.0-rhwp.2',
    'rhwp-hayro-jpeg2000':'0.4.0-rhwp.2', 'rhwp-pdf-import-backend':'0.3.78-rhwp.2',
    'rhwp-qcms':'0.3.0-rhwp.2', 'skia-bindings':'0.157.0', 'skia-safe':'0.157.0',
}


def identities(packages):
    value = sorted((p['name'], p['version'], p.get('source'), p.get('checksum')) for p in packages)
    return hashlib.sha256(json.dumps(value, separators=(',', ':')).encode()).hexdigest()


def resolve(packages, dependency):
    parts = dependency.split(' ')
    if len(parts) not in (1, 2):
        raise ValueError('지원하지 않는 잠금 패키지 참조입니다')
    matches = [p for p in packages if p['name'] == parts[0] and (len(parts) == 1 or p['version'] == parts[1])]
    if len(matches) != 1:
        raise ValueError('잠금 의존성 버전이 없거나 모호합니다')
    return matches[0]


def dependency_edges(packages, originals):
    def identity(package):
        return (package['name'], package['version'], package.get('source'), package.get('checksum'))
    value = sorted((identity(package), sorted(identity(resolve(packages, edge)) for edge in package.get('dependencies', [])))
                   for package in originals if package['name'] != 'rhwp')
    return hashlib.sha256(json.dumps(value, separators=(',', ':')).encode()).hexdigest()


class ComLocksTests(unittest.TestCase):
    def read(self, name):
        path = ROOT/'overlay'/name
        self.assertTrue(path.is_file(), 'COM Windows 의존성이 반영된 CLI 잠금 입력이 필요합니다')
        text = path.read_text(encoding='utf-8')
        value = tomllib.loads(text)
        self.assertEqual(value['version'], 4)
        self.assertEqual(len({(p['name'], p['version'], p.get('source')) for p in value['package']}), len(value['package']))
        return text, value['package']

    def original_graph(self, name, packages):
        # Keep the old independent identity/edge digests. Reverse only exact,
        # reviewed Cargo update records before testing the original graph.
        fixture = json.loads((ROOT/'tests/fixtures/rhwp-0.9.1-cargo-delta.json').read_text())
        self.assertEqual(fixture['schemaVersion'], 1)
        self.assertEqual(fixture['afterRhwpCommit'], json.loads((ROOT/'config/upstream.lock.json').read_text())['rhwp']['commit'])
        delta = fixture['locks'][name]
        allowed = {**RHWP091_UPDATES, **(CLI_NATIVE_UPDATES if name == 'cli-cargo.lock.toml' else {})}
        self.assertEqual({p['name']:p['version'] for p in delta['added']}, allowed)
        self.assertEqual([p['after']['name'] for p in delta['modified']],
                         ['rhwp-native-ffi'] if name == 'cli-cargo.lock.toml' else [])
        self.assertEqual(hashlib.sha256((ROOT/'overlay'/name).read_bytes()).hexdigest(), delta['afterSha256'])
        key = lambda p: (p['name'], p['version'], p.get('source'))
        projected = {key(p): copy.deepcopy(p) for p in packages}
        for change in delta['modified']:
            self.assertEqual(key(change['before']), key(change['after']))
            self.assertEqual(projected[key(change['after'])], change['after'])
            self.assertEqual(set(change['after']['dependencies'])-set(change['before']['dependencies']), {'rhwp-codec-resource'})
            projected[key(change['before'])] = copy.deepcopy(change['before'])
        for expected in delta['added']:
            self.assertEqual(projected.pop(key(expected)), expected, 'Changed package bytes/edges require explicit review')
        renames = {}
        for previous in delta['removed']:
            self.assertNotIn(key(previous), projected)
            projected[key(previous)] = copy.deepcopy(previous)
            current = [p for p in delta['added'] if p['name'] == previous['name']]
            self.assertEqual(len(current), 1)
            renames[(current[0]['name'], current[0]['version'])] = previous['version']
        for package in projected.values():
            edges = []
            for edge in package.get('dependencies', []):
                parts = edge.split(' ')
                if len(parts) == 2 and tuple(parts) in renames:
                    edge = parts[0]+' '+renames[tuple(parts)]
                edges.append(edge)
            if 'dependencies' in package:
                package['dependencies'] = edges
        return list(projected.values())

    def test_reviewed_delta_does_not_admit_unrelated_edge_rebinding(self):
        _, packages = self.read('desktop-cargo.lock.toml')
        for name, old, new in (
            ('iana-time-zone','windows-core 0.61.2','windows-core 0.62.2'),
            ('tauri-utils','toml 0.9.12+spec-1.1.0','toml 1.2.1+spec-1.1.0'),
        ):
            changed = copy.deepcopy(packages)
            node = resolve(changed, name)
            self.assertEqual(node['dependencies'].count(old), 1)
            node['dependencies'] = [new if edge == old else edge for edge in node['dependencies']]
            projected = self.original_graph('desktop-cargo.lock.toml', changed)
            self.assertNotEqual(dependency_edges(projected, projected), ORIGINAL_DESKTOP_EDGES)

    def test_reviewed_delta_rejects_coherent_new_package_checksum_changes(self):
        _, packages = self.read('cli-cargo.lock.toml')
        changed = copy.deepcopy(packages)
        resolve(changed, 'read-fonts 0.47.0')['checksum'] = '0'*64
        with self.assertRaises(AssertionError):
            self.original_graph('cli-cargo.lock.toml', changed)

    def test_both_rhwp_roots_bind_exact_windows_and_windows_core(self):
        for name in ('desktop-cargo.lock.toml', 'cli-cargo.lock.toml'):
            with self.subTest(lock=name):
                _, packages = self.read(name)
                root = resolve(packages, 'rhwp')
                self.assertEqual(root['version'], '0.9.1')
                selected = [edge for edge in root['dependencies']
                            if (resolve(packages, edge)['name'], resolve(packages, edge)['version'])
                            in {('windows', '0.61.3'), ('windows-core', '0.61.2')}]
                self.assertEqual(len(selected), 2, '원 CLI 루트의 두 native Windows 의존성 연결이 필요합니다')
                actual = {(resolve(packages, edge)['name'], resolve(packages, edge)['version']) for edge in selected}
                self.assertEqual(actual, {('windows', '0.61.3'), ('windows-core', '0.61.2')})
                original = self.original_graph(name, packages)
                previous = resolve(original, 'rhwp')
                original_edges = [resolve(original, edge) for edge in previous['dependencies']
                                  if (resolve(original, edge)['name'], resolve(original, edge)['version'])
                                  not in {('windows', '0.61.3'), ('windows-core', '0.61.2')}]
                self.assertEqual(identities(original_edges), ORIGINAL_RHWP_EDGES[name],
                                 '두 native Windows 연결 외의 rhwp 루트 의존성을 보존해야 합니다')

    def test_desktop_keeps_all_original_package_versions_and_checksum_identities(self):
        text, packages = self.read('desktop-cargo.lock.toml')
        self.assertEqual(len(packages), 770)
        self.assertEqual(identities(self.original_graph('desktop-cargo.lock.toml', packages)), ORIGINAL_DESKTOP_IDENTITIES)
        self.assertEqual(resolve(packages, 'hop-desktop')['version'], '0.5.3')
        self.assertEqual(native_activation.validate_lock(text), text)

    def test_cli_adds_only_nine_reviewed_windows_packages_and_keeps_all_original_420(self):
        _, packages = self.read('cli-cargo.lock.toml')
        additions = [p for p in packages if (p['name'], p['version']) in NEW_WINDOWS]
        projected = self.original_graph('cli-cargo.lock.toml', packages)
        original = [p for p in projected if (p['name'], p['version']) not in NEW_WINDOWS]
        self.assertEqual(len(additions), len(NEW_WINDOWS))
        self.assertEqual(len(original), 420)
        self.assertEqual(identities(original), ORIGINAL_CLI_IDENTITIES)
        for package in additions:
            self.assertEqual(package['source'], REGISTRY)
            self.assertEqual(package['checksum'], NEW_WINDOWS[(package['name'], package['version'])])
        self.assertNotIn('opengeul-com-worker', {p['name'] for p in packages})

    def test_every_dependency_reference_resolves_without_ambiguous_windows_versions(self):
        for name in ('desktop-cargo.lock.toml', 'cli-cargo.lock.toml'):
            with self.subTest(lock=name):
                _, packages = self.read(name)
                for package in packages:
                    for edge in package.get('dependencies', []):
                        resolve(packages, edge)

    def test_every_unaffected_desktop_dependency_edge_is_preserved(self):
        _, packages = self.read('desktop-cargo.lock.toml')
        projected = self.original_graph('desktop-cargo.lock.toml', packages)
        self.assertEqual(dependency_edges(projected, projected), ORIGINAL_DESKTOP_EDGES,
                         '기존 패키지 버전 외에 기존 패키지가 선택한 의존성 버전도 보존해야 합니다')
        self.assertIn('heck 0.5.0', resolve(packages, 'snafu-derive 0.9.0')['dependencies'])

    def test_every_unaffected_cli_dependency_edge_is_preserved_after_version_qualification(self):
        _, packages = self.read('cli-cargo.lock.toml')
        projected = self.original_graph('cli-cargo.lock.toml', packages)
        original = [p for p in projected if (p['name'], p['version']) not in NEW_WINDOWS]
        self.assertEqual(dependency_edges(projected, original), ORIGINAL_CLI_EDGES)

    def test_cli_preserves_original_windows62_graph_alongside_new_windows61(self):
        _, packages = self.read('cli-cargo.lock.toml')
        previous = resolve(packages, 'windows 0.62.2')
        current = resolve(packages, 'windows 0.61.3')
        self.assertIn('windows-core 0.62.2', previous['dependencies'])
        self.assertIn('windows-core 0.61.2', current['dependencies'])
        for name in ('windows', 'windows-core', 'windows-future', 'windows-link', 'windows-result', 'windows-strings'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                resolve(packages, name)


if __name__ == '__main__':
    unittest.main()
