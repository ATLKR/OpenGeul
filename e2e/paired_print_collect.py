"""Allowlist exporter; never copies Session logs, images, traces or inputs."""
import hashlib
import json
from pathlib import Path
import struct

from paired_print_contract import integer, require, run_comparison, shape
from paired_print_windows import _parents, read_regular, fingerprint_png

FILE_CAP = 8 * 1024 * 1024
TOTAL_CAP = 48 * 1024 * 1024


def _exact(actual, expected):
    require(type(actual) is type(expected), 26)
    if type(expected) is dict:
        shape(actual, expected)
        for key in expected:
            _exact(actual[key], expected[key])
    elif type(expected) is list:
        require(len(actual) == len(expected), 26)
        for first, second in zip(actual, expected):
            _exact(first, second)
    else:
        require(actual == expected, 26)


def validate_report(report):
    require(type(report) is dict, 26)
    expected = {key: report.get(key) for key in (
        'harnessSourceCommit', 'harnessRunId', 'harnessRunAttempt', 'renderers')}
    require(type(report.get('observations')) is list and len(report['observations']) == 4, 26)
    class Replay:
        index = 0
        def font_snapshot(self):
            return report['fontEnvironment']
        def print_case(self, renderer, fixture):
            result = report['observations'][self.index]
            self.index += 1
            return result
    canonical = run_comparison(expected, report.get('fixtures'), Replay())
    _exact(report, canonical)
    return canonical


def validate_profiles(profiles):
    require(type(profiles) is list and len(profiles) == 4, 26)
    for actual, expected in zip(profiles, ((1, 1), (1, 6), (2, 1), (2, 6))):
        shape(actual, ('roleCode', 'caseCode', 'scopeCode', 'actualSelectedProfileKnown',
                       'volume', 'fileId', 'createdNs'))
        require(type(actual['roleCode']) is int and type(actual['caseCode']) is int
                and (actual['roleCode'], actual['caseCode']) == expected, 26)
        require(type(actual['scopeCode']) is int and actual['scopeCode'] == 1
                and actual['actualSelectedProfileKnown'] is False, 26)
        integer(actual['volume'], 0, 2**128 - 1)
        integer(actual['fileId'], 1, 2**128 - 1)
        integer(actual['createdNs'], 1, 2**128 - 1)


def collect(work, output, report, profiles):
    """Only complete retired pairs can export these four PDFs/four rasters.

    This does not certify the effective WASM/UDF/font choice or any acceptance
    gate. It records sampled processes and their requested profile identities.
    """
    report = validate_report(report)
    validate_profiles(profiles)
    work, output = Path(work).absolute(), Path(output).absolute()
    _parents(output)
    require(not output.exists() and not output.is_symlink(), 26)
    require(work != output and work not in output.parents and output not in work.parents, 26)
    files, total = [], 0
    for observation in report['observations']:
        role, case = observation['roleCode'], observation['caseCode']
        folder = work / f'role-{role}-case-{case}'
        for suffix, path in (('pdf', folder / 'printed.pdf'),
                             ('png', folder / 'pdf-check/page-1.png')):
            data, _ = read_regular(path, FILE_CAP)
            require(hashlib.sha256(data).hexdigest() == observation[suffix + 'Sha256']
                    and len(data) == observation[suffix + 'Bytes'], 26)
            total += len(data)
            require(total <= TOTAL_CAP, 26)
            if suffix == 'pdf':
                require(data.startswith(b'%PDF-') and data.rstrip().endswith(b'%%EOF'), 26)
            else:
                require(len(data) >= 33 and data[:16] == b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR', 26)
                require(list(struct.unpack('>II', data[16:24])) == observation['raster']['pixels'], 26)
                require(fingerprint_png(data) == observation['raster'], 26)
            name = f'role-{role}-case-{case}.{suffix}'
            files.append((name, data))
    result = {'schemaVersion': 1, 'kind': 'paired-print-allowlist',
              'comparison': report, 'requestedProfileScope': 'requested-owned-profile',
              'requestedProfiles': profiles, 'actualSelectedProfileKnown': False,
              'actualSelectedFontIdentityKnown': False, 'actualLoadedWasmIdentityKnown': False,
              'capturedCohortOnly': True, 'qualification': False,
              'files': [{'name': name, 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
                        for name, data in files]}
    metadata = json.dumps(result, ensure_ascii=True, sort_keys=True, separators=(',', ':')).encode('ascii')
    require(len(metadata) <= 128 * 1024 and total + len(metadata) <= TOTAL_CAP, 26)
    output.mkdir()
    for name, data in (*files, ('comparison.numeric.json', metadata + b'\n')):
        with (output / name).open('xb') as stream:
            stream.write(data)
    return result
