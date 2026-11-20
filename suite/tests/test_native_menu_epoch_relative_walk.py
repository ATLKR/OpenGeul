"""Keep complete epoch guards while avoiding repeated relative-path conversion."""
from contextlib import ExitStack, contextmanager
import errno
import importlib
import os
from pathlib import Path
import stat
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT/'suite/e2e'))
from suite.tests import test_native_menu_source_selection as fixtures

OBSERVATIONS = {}


class Clock:
    def __init__(self):
        self.now = 1000.

    def __call__(self):
        return self.now


class RelativeEpochWalkTests(unittest.TestCase):
    def setUp(self):
        self.selection = importlib.import_module('native_menu_source_selection')

    def small_payload(self):
        owner = tempfile.TemporaryDirectory(prefix='owned-epoch-walk-')
        self.addCleanup(owner.cleanup)
        root = Path(owner.name)/'payload'
        registry = root/'Office/share/registry'
        (registry/'deeper').mkdir(parents=True)
        for name in ('A1.xcd', 'deeper/한글.xcd', 'z.xcd'):
            (registry/name).write_bytes(b'')
        return root, registry

    @contextmanager
    def link_case(self, leaf):
        link = leaf.parent/'linked.xcd'
        try:
            link.symlink_to(leaf)
        except OSError as error:
            unsupported = (getattr(error, 'winerror', None) == 1314
                or error.errno in (errno.ENOSYS, errno.ENOTSUP, errno.EOPNOTSUPP))
            if not unsupported:
                raise
            absent = False
            try:
                link.lstat()
            except FileNotFoundError as observation:
                absent = type(observation) is FileNotFoundError and observation.errno == errno.ENOENT
            except (OSError, ValueError):
                pass
            if not absent:
                raise
            original_lstat = Path.lstat
            class LinkMetadata:
                def __init__(self, original):
                    self.original = original
                    self.st_mode = stat.S_IFLNK | stat.S_IMODE(original.st_mode)
                def __getattr__(self, name): return getattr(self.original, name)
            def lstat(path, *args, **kwargs):
                info = original_lstat(path, *args, **kwargs)
                return LinkMetadata(info) if path == leaf else info
            with patch.object(Path, 'lstat', lstat):
                yield 2
        else:
            yield 1

    def test_epoch_keeps_full_order_metadata_checks_without_relative_path_recalculation(self):
        root, _ = self.small_payload()
        relative = ('', 'Office', 'Office/share', 'Office/share/registry',
            'Office/share/registry/A1.xcd', 'Office/share/registry/deeper',
            'Office/share/registry/deeper/한글.xcd', 'Office/share/registry/z.xcd')
        directories = {'', 'Office', 'Office/share', 'Office/share/registry',
            'Office/share/registry/deeper'}
        original_relative, original_posix = Path.relative_to, Path.as_posix
        original_name = self.selection.gate.payload._name
        original_layout = self.selection.gate.payload._layout
        original_ordinary, original_scandir = self.selection._ordinary, os.scandir
        calls = dict(relative=0, posix=0, metadata=0, scandir=0, name=[], layout=[])

        def relative_to(path, *args, **kwargs):
            calls['relative'] += 1
            return original_relative(path, *args, **kwargs)

        def as_posix(path):
            calls['posix'] += 1
            return original_posix(path)

        def name(value):
            calls['name'].append(value)
            return original_name(value)

        def layout(value, *, directory=False):
            calls['layout'].append((value, directory))
            return original_layout(value, directory=directory)

        def ordinary(*args, **kwargs):
            calls['metadata'] += 1
            return original_ordinary(*args, **kwargs)

        def scandir(*args, **kwargs):
            calls['scandir'] += 1
            return original_scandir(*args, **kwargs)

        with patch.object(Path, 'relative_to', relative_to), \
                patch.object(Path, 'as_posix', as_posix), \
                patch.object(self.selection.gate.payload, '_name', name), \
                patch.object(self.selection.gate.payload, '_layout', layout), \
                patch.object(self.selection, '_ordinary', ordinary), \
                patch.object(os, 'scandir', scandir):
            result = self.selection._payload_epoch(root, self.selection.time.monotonic()+150)
        OBSERVATIONS['metadataWalk'] = dict(relativeCalls=calls['relative'],
            asPosixCalls=calls['posix'], metadataCalls=calls['metadata'],
            scandirCalls=calls['scandir'], nameCalls=len(calls['name']),
            layoutCalls=len(calls['layout']), epochEntries=len(result))
        self.assertEqual((calls['relative'], calls['posix']), (0, 0))
        self.assertEqual(calls['metadata'], len(root.parents)+2*len(directories)+3)
        self.assertEqual(calls['scandir'], len(directories))
        self.assertEqual(calls['name'], list(relative[1:]))
        self.assertEqual(calls['layout'], [(name, name in directories) for name in relative[1:]])
        fields = ('st_dev', 'st_ino', 'st_mode', 'st_size', 'st_mtime_ns', 'st_ctime_ns')
        expected = []
        for ancestor in reversed(root.parents):
            info = ancestor.lstat()
            expected.append((str(ancestor), tuple(getattr(info, field) for field in fields[:3])))
        for name in relative:
            path = root/name if name else root
            info = path.lstat()
            expected.append((str(path), tuple(getattr(info, field) for field in fields)))
        self.assertEqual([(row.path, row.identity) for row in result], expected)

    def test_source_selector_keeps_five_seconds_when_relative_conversion_is_the_only_cost(self):
        fixture = fixtures.SourceMenuSelectionTests(
            methodName='test_first_probe_rechecks_inventory_executables_providers_and_pending')
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        prepared = fixture.prepared()
        selected = fixture.selected(prepared)
        process = fixture.launch(selected)
        clock, counts = Clock(), dict(relative=0, posix=0, payload=0, inputs=0, hashes=0, providers=0)
        original_relative, original_posix = Path.relative_to, Path.as_posix
        original_payload = self.selection._payload_epoch
        original_inputs = self.selection._input_epoch
        original_hash = self.selection.gate._hash_file
        original_providers = self.selection.gate.SourceMenuAdmission.verify_provider_files

        def relative_to(path, *args, **kwargs):
            counts['relative'] += 1
            clock.now += .5
            return original_relative(path, *args, **kwargs)

        def as_posix(path):
            counts['posix'] += 1
            clock.now += .5
            return original_posix(path)

        def payload(*args, **kwargs):
            counts['payload'] += 1
            return original_payload(*args, **kwargs)

        def inputs(*args, **kwargs):
            counts['inputs'] += 1
            return original_inputs(*args, **kwargs)

        def hashed(*args, **kwargs):
            counts['hashes'] += 1
            return original_hash(*args, **kwargs)

        def providers(admission, *args, **kwargs):
            counts['providers'] += 1
            return original_providers(admission, *args, **kwargs)

        built = []
        def build(selection):
            built.append(selection)
            return SimpleNamespace(source_selection=selection)

        with patch.object(Path, 'relative_to', relative_to), \
                patch.object(Path, 'as_posix', as_posix), \
                patch.object(self.selection.time, 'monotonic', clock), \
                patch.object(self.selection, '_payload_epoch', payload), \
                patch.object(self.selection, '_input_epoch', inputs), \
                patch.object(self.selection.gate, '_hash_file', hashed), \
                patch.object(self.selection.gate.SourceMenuAdmission, 'verify_provider_files', providers):
            try:
                probe = self.selection.selected_native_menu_probe(process, 1005., clock, build=build)
            except ValueError:
                OBSERVATIONS['fiveSecondSelection'] = dict(counts, finishedAt=clock.now, deadline=1005.)
                self.fail('Relative-path CPU cost consumed the unchanged five-second source action cap')
        OBSERVATIONS['fiveSecondSelection'] = dict(counts, finishedAt=clock.now, deadline=1005.)
        self.assertEqual((clock.now, counts), (1000.,
            dict(relative=0, posix=0, payload=2, inputs=2, hashes=9, providers=1)))
        self.assertEqual(built, [selected])
        self.assertIs(probe.source_selection, selected)

    def test_post_directory_metadata_change_still_rejects(self):
        root, directory = self.small_payload()
        original = self.selection._ordinary
        before, visits = [], []
        def ordinary(path, *args, **kwargs):
            if path == directory:
                visits.append(1)
                if len(visits) == 2:
                    (directory/'new.xcd').write_bytes(b'')
                    os.utime(directory, ns=(before[0].st_atime_ns, before[0].st_mtime_ns+1_000_000_000))
            info = original(path, *args, **kwargs)
            if path == directory and len(visits) == 1:
                before.append(info)
            return info
        with patch.object(self.selection, '_ordinary', ordinary), \
                self.assertRaisesRegex(ValueError, 'directory changed'):
            self.selection._payload_epoch(root, self.selection.time.monotonic()+150)
        self.assertEqual(len(visits), 2)

    def test_new_unsafe_name_case_alias_link_and_reparse_still_reject(self):
        for mode in ('unsafe-name', 'case-alias', 'link', 'reparse'):
            with self.subTest(mode=mode), ExitStack() as patches:
                root, directory = self.small_payload()
                leaf = directory/'A1.xcd'
                if mode == 'unsafe-name':
                    (root/'Unexpected').mkdir()
                elif mode == 'case-alias':
                    alias = directory/'a1.xcd'
                    if not alias.exists():
                        alias.write_bytes(b'')
                    else:  # Windows returns one physical spelling; model a conflicting observed entry.
                        original_scandir = os.scandir
                        class AliasEntry:
                            def __init__(self, original): self.original = original
                            name = 'a1.xcd'
                            def __getattr__(self, name): return getattr(self.original, name)
                        class Entries:
                            def __enter__(self):
                                with original_scandir(directory) as entries:
                                    rows = list(entries)
                                anchor = next(row for row in rows if row.name == 'A1.xcd')
                                return iter([*rows, AliasEntry(anchor)])
                            def __exit__(self, *args): return False
                        def scandir(path):
                            return Entries() if path == directory else original_scandir(path)
                        patches.enter_context(patch.object(os, 'scandir', scandir))
                elif mode == 'link':
                    link_mode = patches.enter_context(self.link_case(leaf))
                    OBSERVATIONS.setdefault('linkGuardModes', []).append(link_mode)
                else:
                    original_lstat = Path.lstat
                    class ReparseMetadata:
                        st_file_attributes = 0x400
                        def __init__(self, original): self.original = original
                        def __getattr__(self, name): return getattr(self.original, name)
                    def lstat(path, *args, **kwargs):
                        info = original_lstat(path, *args, **kwargs)
                        return ReparseMetadata(info) if path == leaf else info
                    patches.enter_context(patch.object(Path, 'lstat', lstat))
                with self.assertRaisesRegex(ValueError, 'unsafe path|case alias|linked or nonregular'):
                    self.selection._payload_epoch(root, self.selection.time.monotonic()+150)

    def test_only_explicit_unsupported_link_errors_can_use_metadata_modeling(self):
        for mode in ('windows-privilege', 'unsupported-api', 'unsupported-filesystem',
                'unexpected-io', 'unexpected-permission', 'partial-outcome'):
            with self.subTest(mode=mode):
                root, directory = self.small_payload()
                leaf = directory/'A1.xcd'
                code = {'unsupported-api': errno.ENOSYS, 'unsupported-filesystem': errno.ENOTSUP,
                    'unexpected-io': errno.EIO}.get(mode, errno.EPERM)
                original = OSError(code, 'Synthetic link creation failure')
                if mode in ('windows-privilege', 'partial-outcome'):
                    original.winerror = 1314
                def create(path, *args, **kwargs):
                    if mode == 'partial-outcome':
                        path.write_bytes(b'')
                    raise original
                with patch.object(Path, 'symlink_to', create):
                    if mode in ('unexpected-io', 'unexpected-permission', 'partial-outcome'):
                        with self.assertRaises(OSError) as caught:
                            with self.link_case(leaf):
                                self.fail('An unknown link outcome cannot enter metadata modeling')
                        self.assertIs(caught.exception, original)
                    else:
                        try:
                            with self.link_case(leaf) as link_mode:
                                self.assertEqual(link_mode, 2)
                                with self.assertRaisesRegex(ValueError, 'linked or nonregular'):
                                    self.selection._payload_epoch(root, self.selection.time.monotonic()+150)
                        except OSError:
                            self.fail('Explicit unsupported link creation must exercise the metadata guard')

    def test_destination_observation_errors_never_authorize_link_metadata_modeling(self):
        for mode in ('absent', 'io-error', 'permission-error', 'invalid-observation', 'wrong-absence'):
            with self.subTest(mode=mode):
                root, directory = self.small_payload()
                leaf, link = directory/'A1.xcd', directory/'linked.xcd'
                primary = OSError(errno.EPERM, 'Synthetic unsupported symlink')
                primary.winerror = 1314
                observed = {'absent': FileNotFoundError(errno.ENOENT, 'Synthetic absence'),
                    'io-error': OSError(errno.EIO, 'Synthetic observation failure'),
                    'permission-error': PermissionError(errno.EPERM, 'Synthetic observation failure'),
                    'invalid-observation': ValueError('Synthetic observation failure'),
                    'wrong-absence': FileNotFoundError(errno.EIO, 'Synthetic wrong absence')}[mode]
                original_path_lstat, original_os_lstat = Path.lstat, os.lstat
                def path_lstat(path, *args, **kwargs):
                    if path == link: raise observed
                    return original_path_lstat(path, *args, **kwargs)
                def os_lstat(path, *args, **kwargs):
                    if Path(path) == link: raise observed
                    return original_os_lstat(path, *args, **kwargs)
                with patch.object(Path, 'symlink_to', side_effect=primary), \
                        patch.object(Path, 'lstat', path_lstat), patch.object(os, 'lstat', os_lstat):
                    if mode == 'absent':
                        with self.link_case(leaf) as link_mode:
                            self.assertEqual(link_mode, 2)
                            with self.assertRaisesRegex(ValueError, 'linked or nonregular'):
                                self.selection._payload_epoch(root, self.selection.time.monotonic()+150)
                    else:
                        with self.assertRaises(OSError) as caught:
                            with self.link_case(leaf):
                                self.fail('An uncertain destination cannot authorize metadata modeling')
                        self.assertIs(caught.exception, primary)


if __name__ == '__main__':
    unittest.main()
