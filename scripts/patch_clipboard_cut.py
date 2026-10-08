"""Bind a delayed text cut to its original document and immutable selection.

Only pinned disposable build sources are patched. Clipboard format/export and
object-level copy/cut remain upstream behavior; no HOP #96 layout claim is made.
"""
from pathlib import Path
import argparse
import hashlib
import json
import os
import tempfile

SOURCE_BLOB = 'b53a3a3797734ce9318f4319951807a8c24d90b6'
TEST_BLOB = '828012ed28a8b8988fc18138a012002a2c7ffddd'
REPLACEMENTS = (
    ("type ClipboardAction = 'copy' | 'cut';", """type ClipboardAction = 'copy' | 'cut';

type ClipboardSelectionSnapshot = {
  selection: string;
  documentGeneration: number;
};"""),
    ("""async function writeSelectedText(
  services: CommandServices,
  inputHandler: ClipboardInputHandler,
): Promise<string | null> {
  const selection = inputHandler.getSelection?.();
  if (!selection) return null;

  const html = copySelectionToWasm(services, selection.start, selection.end);
  const text = services.wasm.getClipboardText();
  const markedHtml = prepareRhwpInternalClipboardHtml(inputHandler, html, text);
  await writeTextHtmlToClipboard(text, markedHtml);
  return serializeSelection(selection);
}""", """async function writeSelectedText(
  services: CommandServices,
  inputHandler: ClipboardInputHandler,
): Promise<ClipboardSelectionSnapshot | null> {
  const selection = inputHandler.getSelection?.();
  if (!selection) return null;

  // Freeze ownership before yielding: another document can reuse these coordinates.
  const snapshot: ClipboardSelectionSnapshot = {
    selection: serializeSelection(selection),
    documentGeneration: services.wasm.documentGeneration,
  };
  const html = copySelectionToWasm(services, selection.start, selection.end);
  const text = services.wasm.getClipboardText();
  const markedHtml = prepareRhwpInternalClipboardHtml(inputHandler, html, text);
  await writeTextHtmlToClipboard(text, markedHtml);
  return snapshot;
}"""),
    ("""        currentSelection &&
        copiedSelection === serializeSelection(currentSelection)""", """        currentSelection &&
        Number.isSafeInteger(copiedSelection.documentGeneration) &&
        copiedSelection.documentGeneration >= 0 &&
        services.wasm.hasLoadedDocument() &&
        copiedSelection.documentGeneration === services.wasm.documentGeneration &&
        services.getInputHandler() === inputHandler &&
        copiedSelection.selection === serializeSelection(currentSelection)"""),
)
TEST_ANCHOR = "  const wasm = {\n    copySelection: vi.fn(),"
TEST_REPLACEMENT = "  const wasm = {\n    documentGeneration: 1,\n    hasLoadedDocument: () => true,\n    copySelection: vi.fn(),"


def transform(text: str) -> str:
    for before, after in REPLACEMENTS:
        if text.count(before) != 1:
            raise ValueError('Clipboard cut source anchor missing, duplicated or already patched')
        text = text.replace(before, after)
    return text


def transform_test(text: str) -> str:
    if text.count(TEST_ANCHOR) != 1:
        raise ValueError('Pinned clipboard test double changed')
    return text.replace(TEST_ANCHOR, TEST_REPLACEMENT)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def git_blob(data: bytes) -> str:
    return hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()


def atomic_write(path: Path, data: bytes) -> None:
    fd, name = tempfile.mkstemp(prefix='.opengeul-cut-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def apply(source: Path) -> None:
    folder = source / 'apps/studio-host/src/command/commands'
    target, tests = folder / 'edit.ts', folder / 'edit.test.ts'
    ledger = source / '.opengeul-overlay.json'
    for path in (target, tests, ledger):
        if path.is_symlink() or not path.is_file():
            raise ValueError('Clipboard patch requires regular source and provenance files')
    state = json.loads(ledger.read_text(encoding='utf-8'))
    if not isinstance(state, dict) or 'clipboardCutGuard' in state:
        raise ValueError('Invalid or already-owned clipboard patch provenance')
    original, test_original = target.read_bytes(), tests.read_bytes()
    if git_blob(original) != SOURCE_BLOB or git_blob(test_original) != TEST_BLOB:
        raise ValueError('Pinned HOP clipboard source or test bytes changed')
    updated = transform(original.decode('utf-8')).encode('utf-8')
    test_updated = transform_test(test_original.decode('utf-8')).encode('utf-8')
    state['clipboardCutGuard'] = {
        'sourceBlob': SOURCE_BLOB, 'testBlob': TEST_BLOB,
        'patcherSha256': sha(Path(__file__).read_bytes()),
        'beforeSha256': sha(original), 'afterSha256': sha(updated),
        'testBeforeSha256': sha(test_original), 'testAfterSha256': sha(test_updated),
        'scope': 'Delayed text cut: same loaded document generation, handler and selection only',
    }
    # All source/anchor checks precede the first write. Build errors remain fatal.
    atomic_write(target, updated)
    atomic_write(tests, test_updated)
    atomic_write(ledger, (json.dumps(state, indent=2) + '\n').encode('utf-8'))
    print('Applied pinned async text-cut ownership guard; runtime verification remains separate.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('source', type=Path)
    apply(parser.parse_args().source.resolve())
