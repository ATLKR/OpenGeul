"""Bind initial equation-dialog focus and preview to their owning opening.

The reviewed transform preserves the 50 ms initial preview and respects a form
control already focused inside the dialog. Native commands/history are unchanged.
"""
from __future__ import annotations
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HELPER = 'scripts/equation_dialog_focus.py'
EDITOR = 'third_party/rhwp/rhwp-studio/src/ui/equation-editor-dialog.ts'
SOURCE_FILES = (EDITOR,)
INPUT_SOURCE_SHA256 = {EDITOR: '1e8c382436302ee88714ba2a57d413ffa9172572f712713ce352ea91cc74fffc'}
OUTPUT_SOURCE_SHA256 = {EDITOR: '76718c71ccb0f20f622d4a1803fcfcf5174249a01bc033d63ccb82dd65cda99e'}
REPLACEMENTS = (
    ('  private previewTimer: ReturnType<typeof setTimeout> | null = null;',
     '  private previewTimer: ReturnType<typeof setTimeout> | null = null;\n  private initialTimer: ReturnType<typeof setTimeout> | null = null;\n  private openGeneration = 0;'),
    ('  open(sec: number, para: number, ci: number, cellIdx?: number, cellParaIdx?: number, noteRef?: NoteControlRef): void {\n    this.build();',
     '  open(sec: number, para: number, ci: number, cellIdx?: number, cellParaIdx?: number, noteRef?: NoteControlRef): void {\n    if (this.initialTimer !== null) {\n      clearTimeout(this.initialTimer);\n      this.initialTimer = null;\n    }\n    const generation = ++this.openGeneration;\n    this.build();'),
    ('    document.body.appendChild(this.overlay);\n    setTimeout(() => {\n      this.scriptArea.focus();\n      this.updatePreview();\n    }, 50);',
     '    document.body.appendChild(this.overlay);\n    const timer = setTimeout(() => {\n      // A queued task belongs to one opening and must preserve a focused form control.\n      if (this.openGeneration !== generation || !this.overlay.isConnected\n          || this.initialTimer !== timer) return;\n      this.initialTimer = null;\n      if (!this.overlay.contains(document.activeElement)) this.scriptArea.focus();\n      this.updatePreview();\n    }, 50);\n    this.initialTimer = timer;'),
    ('  hide(): void {\n    if (this.previewTimer) {',
     '  hide(): void {\n    ++this.openGeneration;\n    if (this.initialTimer !== null) {\n      clearTimeout(this.initialTimer);\n      this.initialTimer = null;\n    }\n    if (this.previewTimer) {'),
)


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def transformed(data: bytes) -> bytes:
    if digest(data) != INPUT_SOURCE_SHA256[EDITOR]:
        raise ValueError('Equation focus reviewed source input changed')
    source = data.decode('utf-8')
    for old, new in REPLACEMENTS:
        if source.count(old) != 1:
            raise ValueError('Equation focus requires exact reviewed source anchors')
        source = source.replace(old, new)
    output = source.encode('utf-8')
    if digest(output) != OUTPUT_SOURCE_SHA256[EDITOR]:
        raise ValueError('Equation focus reviewed source output changed')
    return output


def apply(source: Path) -> dict:
    path = source / EDITOR
    if path.is_symlink() or not path.is_file():
        raise ValueError('Equation focus requires a regular reviewed source')
    output = transformed(path.read_bytes())
    proof = {'beforeSha256': dict(INPUT_SOURCE_SHA256),
             'afterSha256': dict(OUTPUT_SOURCE_SHA256),
             'helperSha256': digest((ROOT / HELPER).read_bytes())}
    validate_contract(proof, {EDITOR: digest(output)},
                      {HELPER: proof['helperSha256']})
    path.write_bytes(output)
    return proof


def validate_contract(proof: dict, prepared_files: dict, helpers: dict) -> None:
    if not isinstance(proof, dict) or set(proof) != {'beforeSha256', 'afterSha256', 'helperSha256'}:
        raise ValueError('Incomplete equation focus proof')
    if proof['beforeSha256'] != INPUT_SOURCE_SHA256 or proof['afterSha256'] != OUTPUT_SOURCE_SHA256:
        raise ValueError('Equation focus reviewed source proof mismatch')
    if not isinstance(prepared_files, dict) or prepared_files.get(EDITOR) != OUTPUT_SOURCE_SHA256[EDITOR]:
        raise ValueError('Equation focus prepared source mismatch')
    expected = helpers.get(HELPER) if isinstance(helpers, dict) else None
    if expected != digest((ROOT / HELPER).read_bytes()) or proof['helperSha256'] != expected:
        raise ValueError('Equation focus helper proof mismatch')
