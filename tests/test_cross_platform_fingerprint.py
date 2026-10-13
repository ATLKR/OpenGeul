"""실제 같은 파일 바이트를 POSIX/Windows 경로 비교 순서로 각각 읽는다."""
from pathlib import Path, PurePosixPath, PureWindowsPath
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'scripts'), str(ROOT / 'e2e'), str(ROOT / 'tests')]
import release_pair
import store_qualification
import test_release_pair as fixtures


class PosixOrderedPath(type(Path())):
    def __lt__(self, other):
        return PurePosixPath(str(self)) < PurePosixPath(str(other))


class WindowsOrderedPath(type(Path())):
    def __lt__(self, other):
        return PureWindowsPath(str(self)) < PureWindowsPath(str(other))


class CrossPlatformFingerprintTests(unittest.TestCase):
    def test_verified_source22_fingerprint_matches_both_path_orderings(self):
        fixture = fixtures.ReleasePairTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.assemble()
        directory = fixture.output
        originals = {p.name: p.read_bytes() for p in directory.iterdir()}
        self.assertEqual(len(originals), 22)
        posix = PosixOrderedPath(directory)
        windows = WindowsOrderedPath(directory)
        self.assertNotEqual([p.name for p in sorted(posix.iterdir())], [p.name for p in sorted(windows.iterdir())])
        self.assertEqual(release_pair.source_fingerprint(posix), release_pair.source_fingerprint(windows))
        self.assertEqual({p.name: p.read_bytes() for p in directory.iterdir()}, originals)

    def test_store_fingerprint_matches_both_path_orderings(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            (directory / 'Z-source.json').write_bytes(b'source')
            (directory / 'a-install.json').write_bytes(b'install')
            posix = PosixOrderedPath(directory)
            windows = WindowsOrderedPath(directory)
            self.assertNotEqual([p.name for p in sorted(posix.iterdir())], [p.name for p in sorted(windows.iterdir())])
            self.assertEqual(store_qualification._fingerprint(posix), store_qualification._fingerprint(windows))

    def test_same_size_byte_changes_still_change_both_fingerprints(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            (directory / 'Z-source.json').write_bytes(b'source')
            target = directory / 'a-install.json'
            target.write_bytes(b'install')
            posix = PosixOrderedPath(directory)
            windows = WindowsOrderedPath(directory)
            original = (store_qualification._fingerprint(posix), store_qualification._fingerprint(windows))
            target.write_bytes(b'changed')
            changed = (store_qualification._fingerprint(posix), store_qualification._fingerprint(windows))
            self.assertNotEqual(original[0], changed[0])
            self.assertNotEqual(original[1], changed[1])


if __name__ == '__main__':
    unittest.main()
