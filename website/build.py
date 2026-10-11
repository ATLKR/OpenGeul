import base64
import hashlib
import json
from pathlib import Path
import shutil
import sys

source = Path(__file__).resolve().parent
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
(output / 'assets.mjs').write_text('export default ' + json.dumps(assets) + ';\n', encoding='utf-8')
shutil.copyfile(source / 'worker.mjs', output / 'worker.mjs')
print(f'Bundled {len(assets)} public assets for Cloudflare Worker upload.')
