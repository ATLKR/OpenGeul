"""Acquire pinned intact language FOD CABs from official Server 2025 media.

Language FODs have no satellites (Microsoft Features on Demand documentation).
The original Server metadata/CompDB paths are preserved with the two complete
language CABs. Actual DISM -Source/-LimitAccess and capability read-back must
prove whether this source is sufficient; acquisition is never IME readiness.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import time
import urllib.request

ISO_URL = 'https://software-static.download.prss.microsoft.com/dbazure/888969d5-f34g-4e03-ac9d-1f9786c66749/26100.1.240331-1435.ge_release_amd64fre_SERVER_LOF_PACKAGES_OEM.iso'
ISO_BYTES = 6864345088
OFFICIAL_LINK = 'https://go.microsoft.com/fwlink/?linkid=2273506'
DOCUMENTATION = (
    'https://www.microsoft.com/en-us/evalcenter/evaluate-windows-server-2025',
    'https://learn.microsoft.com/en-us/windows-server/get-started/server-core-app-compatibility-feature-on-demand',
    'https://learn.microsoft.com/en-us/windows-hardware/manufacture/desktop/features-on-demand-v2--capabilities',
    'https://learn.microsoft.com/en-us/powershell/module/dism/add-windowscapability?view=windowsserver2025-ps',
)
# Coordinates and digests were observed by reading this official UDF ISO over
# HTTPS and inspecting the actual complete CABs, not from third-party repacks.
# Digests pin our observed bytes; they are not publisher-listed ISO checksums.
PACKAGES = [
    {
        "relativePath": "LanguagesAndOptionalFeatures/Microsoft-Windows-LanguageFeatures-Fonts-Kore-Package~31bf3856ad364e35~amd64~~.cab",
        "start": 1431003136,
        "bytes": 9748860,
        "sha256": "d6cf56321dde503390a3f448b090b6dec70f6a9270573b51b376c092a3314f34"
    },
    {
        "relativePath": "LanguagesAndOptionalFeatures/Microsoft-Windows-LanguageFeatures-Basic-ko-kr-Package~31bf3856ad364e35~amd64~~.cab",
        "start": 805877760,
        "bytes": 9744372,
        "sha256": "0c66033dfc692605c7887cd6ad3cf02366e5e0dcf1f130a81c4a19b174e1dfd2"
    },
    {
        "relativePath": "LanguagesAndOptionalFeatures/Microsoft-Windows-FodMetadataServicing-Server-Metadata-Package.cab",
        "start": 258222080,
        "bytes": 460849,
        "sha256": "25d2b8449d77b0f2f395ca3e0bfd00eba888301cd8eeaea9100880be71ff51c4"
    },
    {
        "relativePath": "LanguagesAndOptionalFeatures/Microsoft-Windows-FodMetadataServicing-Server-CompDB-Package.cab",
        "start": 258050048,
        "bytes": 171839,
        "sha256": "8aa109fd5a7112ca78114a46b526aad88301b21a3ffc0a59ccb1b04f74f99c7a"
    },
    {
        "relativePath": "LanguagesAndOptionalFeatures/FoDMetadata_Client.cab",
        "start": 11231232,
        "bytes": 510772,
        "sha256": "b825461369a531e76f3dda84840ec457d5f8062afd84381dd40938f69a60305b"
    },
    {
        # The neutral Build CompDB maps language features to their canonical
        # CAB payloads. The separate Metadata CompDB contains descriptions.
        "relativePath": "LanguagesAndOptionalFeatures/metadata/ServerTargetCompDB_FOD_Neutral.xml.cab",
        "start": 6193278976,
        "bytes": 47763,
        "sha256": "057bcf0ac6d870ba9fca2b60aa40e78c901e4a3ffafea5b7b567c06d89bf632e"
    },
    {
        "relativePath": "LanguagesAndOptionalFeatures/metadata/ServerTargetCompDB_FOD_Metadata_Neutral.xml.cab",
        "start": 6192836608,
        "bytes": 441350,
        "sha256": "37a9f5761b2c17e2abc60706a74d6422620c17264e8be44025689814fb02d6ef"
    },
    {
        "relativePath": "LanguagesAndOptionalFeatures/metadata/ServerTargetCompDBForISO_ko-KR.xml.cab",
        "start": 6192582656,
        "bytes": 10573,
        "sha256": "7fabab57ea8eaddb593b63178c9422fa6a2c129d428304af40e3e125c230dc83"
    },
    {
        "relativePath": "LanguagesAndOptionalFeatures/metadata/ServerTargetCompDBForISO_FOD_ko-KR.xml.cab",
        "start": 6191998976,
        "bytes": 17675,
        "sha256": "ebfe30e2fab9c5c1985ce69a08d59684446ddf29c5d3e4a41a79c64264cbde50"
    }
]


def require_plain_path(path):
    path = Path(path).absolute()
    for item in (path, *path.parents):
        if item.is_symlink() or getattr(item, 'is_junction', lambda: False)():
            raise ValueError('FOD source paths must not contain links or junctions')
    return path


def download_package(package, output, opener=None):
    relative = PurePosixPath(package['relativePath'])
    start, size, expected_digest = package['start'], package['bytes'], package['sha256']
    if (relative.is_absolute() or '..' in relative.parts or not relative.parts
            or relative.parts[0] != 'LanguagesAndOptionalFeatures'
            or any(not re.fullmatch('[A-Za-z0-9_.~+-]+', part) for part in relative.parts)
            or relative.suffix.lower() != '.cab'):
        raise ValueError('Only intact CABs inside the owned FOD source directory are accepted')
    if (type(start) is not int or type(size) is not int or start < 0
            or not 0 < size <= 32 * 1024**2 or start + size > ISO_BYTES
            or not re.fullmatch('[0-9a-f]{64}', expected_digest)):
        raise ValueError('FOD range coordinates, size or digest are invalid')
    output = require_plain_path(output)
    destination = require_plain_path(output.joinpath(*relative.parts))
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists(): raise FileExistsError('Preserve the existing FOD source CAB: ' + destination.name)
    request = urllib.request.Request(ISO_URL, headers={'Range': f'bytes={start}-{start + size - 1}'})
    request_start = time.monotonic()
    with (opener or urllib.request.urlopen)(request, timeout=30) as response:
        if (response.status != 206 or response.geturl() != ISO_URL
                or response.headers.get('Content-Range') != f'bytes {start}-{start + size - 1}/{ISO_BYTES}'
                or response.headers.get('Content-Length') != str(size)):
            raise ValueError('Official ISO server did not return the exact pinned byte range')
        digest, observed = hashlib.sha256(), 0
        with destination.open('xb') as stream:
            while observed < size:
                if time.monotonic() - request_start > 90:
                    raise TimeoutError('A pinned official FOD range exceeded its ninety-second bound')
                payload = response.read(min(1024 * 1024, size - observed))
                if not payload: raise ValueError('Official FOD range was truncated')
                observed += len(payload)
                if observed > size: raise ValueError('Official FOD range exceeded the pinned size')
                digest.update(payload)
                stream.write(payload)
            if response.read(1): raise ValueError('Official FOD range contains extra bytes')
        if digest.hexdigest() != expected_digest:
            raise ValueError('Official FOD range differs from the pinned observed CAB digest')
    return {'relativePath': relative.as_posix(), 'rangeStart': start, 'rangeEnd': start + size - 1,
            'bytes': observed, 'sha256': digest.hexdigest()}


def acquire(output):
    output = require_plain_path(output)
    output.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    record = {'formatVersion': 1, 'suiteOnly': True, 'productInputVerified': False,
              'storeQualified': False, 'officialLink': OFFICIAL_LINK, 'isoUrl': ISO_URL,
              'isoBytes': ISO_BYTES, 'publisherListedIsoSha256': None,
              'digestKind': 'pinned observed complete CAB bytes acquired from official Microsoft TLS media',
              'documentation': DOCUMENTATION, 'packages': [], 'success': False}
    try:
        for package in PACKAGES:
            if time.monotonic() - started > 240: raise TimeoutError('Official FOD source acquisition exceeded four minutes')
            record['packages'].append(download_package(package, output))
        record.update(success=True, sourceDirectory=str(output / 'LanguagesAndOptionalFeatures'))
        return record
    except Exception as exc:
        record['error'] = type(exc).__name__ + ': ' + str(exc)
        raise
    finally:
        record['elapsedSeconds'] = round(time.monotonic() - started, 3)
        (output / 'source-acquisition.json').write_text(json.dumps(record, indent=2), encoding='utf-8')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    print(json.dumps(acquire(args.output), indent=2), flush=True)
    return 0


if __name__ == '__main__': raise SystemExit(main())
