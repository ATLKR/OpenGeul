import base64
import hashlib
import json
from pathlib import Path
import shutil
import sys

source = Path(__file__).resolve().parent
sys.path.insert(0, str(source.parent / 'scripts'))
from store_release_status import badge_svg, decode_metadata, encode_metadata

with (source / 'store-release.json').open('rb') as stream:
    metadata = decode_metadata(stream.read(8193))
output = Path(sys.argv[1])
output.mkdir(parents=True, exist_ok=True)
files = {'index.html': 'text/html; charset=utf-8', 'privacy.html': 'text/html; charset=utf-8',
         'assets/style.css': 'text/css; charset=utf-8', 'assets/opengeul-editor.png': 'image/png',
         'assets/opengeul-logo.png': 'image/png'}
assets = {}
for name, content_type in files.items():
    data = (source / name).read_bytes()
    assets['/' + name] = {'type': content_type, 'base64': base64.b64encode(data).decode(),
                         'sha256': hashlib.sha256(data).hexdigest()}
for route, data, content_type in (
        ('/api/store-release.json', encode_metadata(metadata), 'application/json; charset=utf-8'),
        ('/assets/store-version.svg', badge_svg(metadata), 'image/svg+xml; charset=utf-8')):
    assets[route] = {'type': content_type, 'base64': base64.b64encode(data).decode(),
                     'sha256': hashlib.sha256(data).hexdigest()}
(output / 'assets.mjs').write_text('export default ' + json.dumps(assets) + ';\n', encoding='utf-8')
shutil.copyfile(source / 'worker.mjs', output / 'worker.mjs')
print(f'Bundled {len(assets)} public assets for Cloudflare Worker upload.')
