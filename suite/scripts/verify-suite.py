"""Verify a prepared Suite against its complete stored inventory."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from payload import verify_payload

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('directory', type=Path)
args = parser.parse_args()
receipt = json.loads((args.directory/'suite-inventory.json').read_text(encoding='utf-8'))
verify_payload(args.directory, receipt)
print('Suite inventory, source, branding, licenses and architecture verified.')
