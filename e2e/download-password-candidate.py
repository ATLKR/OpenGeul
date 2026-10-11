"""Read-only, fixed-source transport for a separate native UI qualification."""
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import zipfile
from prepare_payload import inventory, stream_hash

REPO = 'ATLKR/OpenGeul'
RUN = 38142625600
SHA = '756116ff1fc094e8a1bdf2ecec6fcf3f6d3c4e17'

def gh(*args):
    result = subprocess.run(['gh', *args], capture_output=True, text=True, encoding='utf-8', timeout=240)
    if result.returncode:
        raise RuntimeError('Fixed-source GitHub read/download failed; credentials and redirect URLs omitted')
    return result.stdout

run = json.loads(gh('api', f'repos/{REPO}/actions/runs/{RUN}'))
assert run['id'] == RUN and run['head_sha'] == SHA and run['run_attempt'] == 1
assert run['event'] == 'workflow_dispatch' and run['path'] == '.github/workflows/msix.yml'
for field in ('repository', 'head_repository'):
    assert run[field]['full_name'] == REPO and run[field]['private'] is False
jobs = json.loads(gh('api', f'repos/{REPO}/actions/runs/{RUN}/jobs?per_page=100'))
assert jobs['total_count'] == len(jobs['jobs'])
for name in ('wasm', 'build'):
    selected = [j for j in jobs['jobs'] if j['name'] == name]
    assert len(selected) == 1 and selected[0]['status'] == 'completed' and selected[0]['conclusion'] == 'success'
artifacts = json.loads(gh('api', f'repos/{REPO}/actions/runs/{RUN}/artifacts?per_page=100'))
assert artifacts['total_count'] == len(artifacts['artifacts'])
records = []
for prefix, directory, limit in [('opengeul-windows-x64', 'package', 97),
                                 ('opengeul-wasm', 'wasm-input', 33),
                                 ('opengeul-e2e-inputs', 'inputs', 17)]:
    name = f'{prefix}-{RUN}'
    selected = [a for a in artifacts['artifacts'] if a['name'] == name]
    assert len(selected) == 1
    item = selected[0]
    assert item['expired'] is False and 0 < item['size_in_bytes'] <= limit * 1024 * 1024
    assert item['workflow_run']['id'] == RUN and item['workflow_run']['head_sha'] == SHA
    assert item['digest'].startswith('sha256:') and len(item['digest']) == 71
    assert not Path(directory).exists()
    # Fetch the selected immutable ID, then check the actual ZIP against its API digest.
    # Capture all stderr: failures must not print temporary signed redirect URLs.
    with tempfile.TemporaryDirectory(prefix='opengeul-password-transport-') as temp:
        path = Path(temp) / 'artifact.zip'
        with path.open('xb') as output:
            result = subprocess.run(['gh', 'api', f'repos/{REPO}/actions/artifacts/{item["id"]}/zip'],
                                    stdout=output, stderr=subprocess.PIPE, timeout=240)
        if result.returncode:
            raise RuntimeError('Fixed artifact download failed; redirect URLs omitted')
        assert path.stat().st_size == item['size_in_bytes']
        with path.open('rb') as data:
            digest = stream_hash(data)
        assert 'sha256:' + digest == item['digest']
        with zipfile.ZipFile(path) as archive:
            entries = inventory(archive)
            assert sum(e.file_size for e in entries.values()) <= limit * 1024 * 1024
            for member, entry in entries.items():
                target = Path(directory).joinpath(*member.split('/'))
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(entry) as source, target.open('xb') as output:
                    shutil.copyfileobj(source, output, 1024 * 1024)
    records.append({**{k: item[k] for k in ('id', 'name', 'size_in_bytes', 'digest')}, 'verifiedArchiveSha256': digest})
provenance = json.loads(Path('package/provenance.json').read_text(encoding='utf-8-sig'))
assert provenance['repository'] == REPO and provenance['commit'] == SHA and str(provenance['runId']) == str(RUN)
assert provenance['version'] == '1.1.2'
Path('evidence').mkdir(exist_ok=True)
Path('evidence/source.json').write_text(json.dumps({'sourceRun': RUN, 'sourceCommit': SHA, 'artifacts': records}, indent=2) + '\n')
print('Downloaded the fixed successful source build and its same-run WASM/own synthetic fixtures.')
