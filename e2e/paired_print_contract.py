"""Nonqualifying paired-print contract. This module performs no OS operations."""
import copy
import re

LEGACY_SOURCE = '131ccbf3ac10a82e1d6785b4c906fb836b912e73'
LEGACY_EDITOR = 'aa34b05cd63cef8fe880ca3697661270d47afd42bf5ce1e0b7c3b6f5f3450be8'
LEGACY_WASM = 'd5455ff80f61af65dfab5cbe2f2058bc377e5d44f7c97dd7e586f0edaaa6d5da'
LEGACY_JS = '70cde06a369fa7fd4fc8bc8f3d6acaee158596ba1a116a2c72159002b0b5654e'
CASE_CODES = (1, 6)


class Rejected(ValueError):
    """A closed numeric code; never stores source/error/argument text."""
    def __init__(self, code=1):
        self.code = code
        super().__init__(code)


def require(condition, code=1):
    if not condition:
        raise Rejected(code)


def integer(value, low=0, high=2**63 - 1):
    require(type(value) is int and low <= value <= high)
    return value


def digest(value, length=64):
    require(type(value) is str and re.fullmatch('[0-9a-f]{' + str(length) + '}', value) is not None)
    require(value != '0' * length)
    return value


def shape(value, keys):
    require(type(value) is dict and set(value) == set(keys))


def expected_renderers(*, harness_source, run_id, attempt,
                       current_editor_sha256, current_editor_bytes,
                       current_wasm_sha256, current_js_sha256):
    """Expected values come from the independent caller/package admission."""
    digest(harness_source, 40)
    require(harness_source != LEGACY_SOURCE)
    integer(run_id, 1)
    integer(attempt, 1)
    for value in (current_editor_sha256, current_wasm_sha256, current_js_sha256):
        digest(value)
    integer(current_editor_bytes, 1, 96 * 1024 * 1024)
    require(current_editor_sha256 != LEGACY_EDITOR)
    require(current_wasm_sha256 != LEGACY_WASM and current_js_sha256 != LEGACY_JS)
    shared = {'harnessSourceCommit': harness_source,
              'harnessRunId': run_id, 'harnessRunAttempt': attempt}
    return {
        **shared,
        'renderers': [
            {**shared, 'roleCode': 1, 'label': 'locked-hwp114',
             'appSourceCommit': LEGACY_SOURCE, 'rhwpVersion': '0.8.7',
             'executableSha256': LEGACY_EDITOR, 'executableBytes': 36402688,
             'wasmSha256': LEGACY_WASM, 'jsSha256': LEGACY_JS},
            {**shared, 'roleCode': 2, 'label': 'current',
             'appSourceCommit': harness_source, 'rhwpVersion': '0.9.0',
             'executableSha256': current_editor_sha256,
             'executableBytes': current_editor_bytes,
             'wasmSha256': current_wasm_sha256, 'jsSha256': current_js_sha256},
        ],
    }


def validate_expected(value):
    shape(value, ('harnessSourceCommit', 'harnessRunId', 'harnessRunAttempt', 'renderers'))
    renderers = value['renderers']
    require(type(renderers) is list and len(renderers) == 2)
    require(type(renderers[1]) is dict)
    current = renderers[1]
    # Rebuild the independent expected structure; no observation chooses its role.
    rebuilt = expected_renderers(
        harness_source=value['harnessSourceCommit'], run_id=value['harnessRunId'],
        attempt=value['harnessRunAttempt'],
        current_editor_sha256=current.get('executableSha256'),
        current_editor_bytes=current.get('executableBytes'),
        current_wasm_sha256=current.get('wasmSha256'),
        current_js_sha256=current.get('jsSha256'))
    require(value == rebuilt)
    for actual, canonical in zip(renderers, rebuilt['renderers']):
        shape(actual, canonical)
        require(all(type(actual[key]) is type(canonical[key]) for key in canonical))
    return copy.deepcopy(rebuilt)


def validate_fixtures(fixtures):
    require(type(fixtures) is list and len(fixtures) == 2)
    for row in fixtures:
        shape(row, ('caseCode', 'sha256', 'bytes'))
        integer(row['caseCode'], 1, 8)
        digest(row['sha256'])
        integer(row['bytes'], 1, 20 * 1024 * 1024)
    require(tuple(row['caseCode'] for row in fixtures) == CASE_CODES)
    return copy.deepcopy(fixtures)


def validate_fonts(value):
    shape(value, ('scopeCode', 'files'))
    require(type(value['scopeCode']) is int and value['scopeCode'] == 1)
    rows = value['files']
    require(type(rows) is list and len(rows) == 2)
    require([row.get('fontCode') for row in rows] == [1, 2])
    for row in rows:
        shape(row, ('fontCode', 'present', 'bytes', 'sha256', 'volume', 'fileId', 'modifiedNs'))
        integer(row['fontCode'], 1, 2)
        require(type(row['present']) is bool)
        for key in ('volume', 'fileId', 'modifiedNs'):
            integer(row[key], 0, 2**128 - 1)
        if row['present']:
            integer(row['bytes'], 1, 32 * 1024 * 1024)
            digest(row['sha256'])
            require(row['fileId'] > 0)
        else:
            require(row['bytes'] == 0 and type(row['bytes']) is int
                    and row['sha256'] is None
                    and all(row[key] == 0 for key in ('volume', 'fileId', 'modifiedNs')))
    return copy.deepcopy(value)


def validate_raster(value):
    shape(value, ('pixels', 'bbox', 'ink', 'maskSha256'))
    require(type(value['pixels']) is list and len(value['pixels']) == 2)
    require(type(value['bbox']) is list and len(value['bbox']) == 4)
    width, height = [integer(x, 1, 12000) for x in value['pixels']]
    x0, y0, x1, y1 = [integer(x, 0, 12000) for x in value['bbox']]
    require(0 <= x0 < x1 <= width and 0 <= y0 < y1 <= height)
    integer(value['ink'], 100, width * height)
    digest(value['maskSha256'])


OBSERVATION_KEYS = (
    'roleCode', 'caseCode', 'harnessSourceCommit', 'harnessRunId',
    'harnessRunAttempt', 'appSourceCommit', 'executableSha256', 'executableBytes',
    'wasmProvenanceSha256', 'fixtureBeforeSha256', 'fixtureAfterSha256',
    'pdfCreated', 'spoolerCompleted', 'paperValidated', 'originalOraclePassed',
    'primaryErrorCode', 'raster', 'retainedRootExited', 'retainedWebviewCount',
    'retainedWebviewsExited', 'cleanupMayBeForced', 'pdfSha256', 'pdfBytes',
    'pngSha256', 'pngBytes',
)


def validate_observation(value, expected, fixture):
    shape(value, OBSERVATION_KEYS)
    for key in ('roleCode', 'harnessSourceCommit', 'harnessRunId',
                'harnessRunAttempt', 'appSourceCommit', 'executableSha256', 'executableBytes'):
        require(type(value[key]) is type(expected[key]) and value[key] == expected[key], 2)
    require(type(value['caseCode']) is int and value['caseCode'] == fixture['caseCode'], 3)
    require(value['wasmProvenanceSha256'] == expected['wasmSha256'], 4)
    require(value['fixtureBeforeSha256'] == value['fixtureAfterSha256'] == fixture['sha256'], 5)
    for key in ('pdfCreated', 'spoolerCompleted', 'paperValidated', 'originalOraclePassed',
                'retainedRootExited', 'retainedWebviewsExited', 'cleanupMayBeForced'):
        require(type(value[key]) is bool)
    require(value['pdfCreated'] and value['spoolerCompleted'] and value['paperValidated'], 6)
    require(value['retainedRootExited'] and value['retainedWebviewsExited'], 7)
    require(value['cleanupMayBeForced'] is True)
    integer(value['retainedWebviewCount'], 1, 64)
    integer(value['primaryErrorCode'], 0, 1)
    require(value['originalOraclePassed'] == (value['primaryErrorCode'] == 0), 8)
    validate_raster(value['raster'])
    for prefix in ('pdf', 'png'):
        digest(value[prefix + 'Sha256'])
        integer(value[prefix + 'Bytes'], 1, 8 * 1024 * 1024)
    return copy.deepcopy(value)


def run_comparison(expected, fixtures, port):
    """Preserve observed oracle failures; never authorize a package or a release."""
    expected = validate_expected(expected)
    fixtures = validate_fixtures(fixtures)
    fonts = validate_fonts(port.font_snapshot())
    observations = []
    for renderer in expected['renderers']:
        for fixture in fixtures:
            raw = port.print_case(copy.deepcopy(renderer), copy.deepcopy(fixture))
            observations.append(validate_observation(raw, renderer, fixture))
            require(validate_fonts(port.font_snapshot()) == fonts, 9)
    all_passed = all(row['originalOraclePassed'] for row in observations)
    return {
        'schemaVersion': 1, 'kind': 'paired-virtual-print-diagnostic',
        'harnessSourceCommit': expected['harnessSourceCommit'],
        'harnessRunId': expected['harnessRunId'], 'harnessRunAttempt': expected['harnessRunAttempt'],
        'renderers': expected['renderers'], 'fixtures': fixtures,
        'fontEnvironment': fonts, 'actualSelectedFontIdentityKnown': False,
        'sampledFontFilesStable': True, 'observations': observations,
        'observationComplete': True, 'originalOracleAllPassed': all_passed,
        'legacyIsGoldenProducer': False, 'sourceQualified': False,
        'acceptanceEligible': False, 'qualification': False,
        'exitCode': 0 if all_passed else 1,
    }
