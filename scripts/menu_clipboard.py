"""Install the reviewed menu paste path after the three clipboard lifecycle guards."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re

from buildkit import ROOT, replace_once

ENGINE = 'third_party/rhwp/rhwp-studio/src/engine/'
HANDLER = ENGINE + 'input-handler.ts'
KEYBOARD = ENGINE + 'input-handler-keyboard.ts'
HELPER = ENGINE + 'opengeul-menu-clipboard.ts'
LIB = 'apps/desktop/src-tauri/src/lib.rs'
WINDOWS = 'apps/desktop/src-tauri/src/windows.rs'
CONFIG = 'apps/desktop/src-tauri/tauri.windows.conf.json'
INPUT_SOURCE_SHA256 = {
    HANDLER: '6b88aaae0cb18f742957733ed9f39264bd5345f5622348ce840e3eb89598155e',
    KEYBOARD: '6d9e30cd4398beefed92f86fda6e331ac0e5c0876424b620076a344bbc50de49',
}
SOURCE_FILES = (HANDLER, KEYBOARD, LIB, WINDOWS, CONFIG)
INPUT_NATIVE_SHA256 = {
    LIB: '829760469830430e2eb4b5e9f261df107b99fdd3df9a8936fcf14dacf17807e7',
    WINDOWS: '48867dee2c8a52d520978c84584d19ba763ec5eaddf8630460f4c68ecc632646',
    CONFIG: 'f5f3375de3e0c5763183e1d488a73272d44ef5598051515031d34c2f2d62004d',
}
LIB_HWPX_INPUT_SHA256 = '01c0c8410f3c9fb7536a5faecefbd2270d843de686535c8caff1d1bdbf85f43e'
INPUT_NATIVE_CRLF_SHA256 = {
    LIB: 'b6f7d461cb84c7597ba1cf9fea5966e07844a3445fc8b9b014ad4af73905f0b5',
    WINDOWS: 'a29883ffc8456443177569b4c84f3c6720cbc13da1aface53c6cf713af12a5ed',
    CONFIG: '12cfb90e024deab346830c5341c54efec7c0e4410ec20ab63873d402720282d1',
}
LIB_HWPX_CRLF_INPUT_SHA256 = '44f3dca491b82b7c8eb6098d31680b2284867067783bd99eacdd8ae08ed85fb5'
PHASE_SOURCE_SHA256 = {
    'prepared': {
        HANDLER: 'ee144804d21ea5585fc03e5057317310990197c3b096c9aa34caa8006299d3c8',
        KEYBOARD: '38d1adba2457b1442dad03d75395a0fb882881af5f5efe63be5e5c93867465ca',
        LIB: 'b967a6f9b790cc287b7f6b64a48d187a79877d055ed60c8875380a50f2af7a4f',
        WINDOWS: '6e9f1bf1edf1ef16a7a1af1050cc2bcdc8334e7ed33b27645136c5facc868461',
        CONFIG: 'd01152999d6a0454488c13b6447a2a63e86674ae8f69f98ca42ea8953c1feec0',
    },
}
PHASE_SOURCE_SHA256['hwpx'] = {
    **PHASE_SOURCE_SHA256['prepared'],
    LIB: '2e46387729bd71243bee989cc57602f2d9f3fd3547666b3e6d118c91e0f188ed',
}
PHASE_SOURCE_SHA256['hwpx-windows'] = {
    **PHASE_SOURCE_SHA256['hwpx'],
    LIB: '4d8ae5ce4845e98664ed9e3dc653523287d3f69c4b490979ba1dab5484fa1a99',
}
SHA = re.compile(r'[0-9a-f]{64}\Z')

HANDLER_IMPORT = "import * as _keyboard from './input-handler-keyboard';"
OLD_MENU_PASTE = '''  performPaste(): boolean {
    if (this.editMode === 'form') return false;
    this.focusTextarea();
    return document.execCommand('paste');
  }'''
NEW_MENU_PASTE = '''  performPaste(): Promise<boolean> {
    return performMenuPaste(this);
  }'''
OLD_PLAIN_PASTE = '''function pastePlainText(this: any, text: string, hasSelection: boolean): void {
  if (hasSelection) {
    this.deleteSelection({ deferRecord: true });
  }
  if (!text) return;

  const lines = text.split(/\\r?\\n/);
  for (let i = 0; i < lines.length; i++) {
    if (lines[i]) {
      this.executeOperation({ kind: 'command', command: new InsertTextCommand(this.cursor.getPosition(), lines[i]) });
    }
    if (i < lines.length - 1) {
      const position = this.cursor.getPosition();
      const command = this.cursor.isInCell()
        ? new SplitParagraphInCellCommand(position)
        : new SplitParagraphCommand(position);
      this.executeOperation({ kind: 'command', command });
    }
  }
}'''
NEW_PLAIN_PASTE = '''function pastePlainText(this: any, text: string, hasSelection: boolean): void {
  // An empty clipboard leaves the selection and history unchanged.
  if (!text) return;
  const lines = text.split(/\\r?\\n/);
  // Replacement and all pasted lines form one undo step, separate from prior typing.
  this.executeOperation({ kind: 'snapshot', operationType: 'pastePlainText', operation: (wasm: WasmBridge) => {
    if (hasSelection) this.deleteSelection({ deferRecord: true });
    for (let i = 0; i < lines.length; i++) {
      if (lines[i]) {
        const position = this.cursor.getPosition();
        const keepFieldStartOutside = this.isExitedFieldStartPosition(position);
        if (keepFieldStartOutside) wasm.clearActiveField();
        const command = new InsertTextCommand(position, lines[i]);
        const after = command.execute(wasm);
        this.prepareTextMutationBeforeCursor(command.consumeTextMutationEffects());
        this.cursor.moveTo(after);
        this.cursor.resetPreferredX();
        this.advancePendingCharShapeAnchor(position, after);
        if (keepFieldStartOutside) this.markCurrentFieldStartOutside();
      }
      if (i < lines.length - 1) {
        const position = this.cursor.getPosition();
        const command = this.cursor.isInCell()
          ? new SplitParagraphInCellCommand(position)
          : new SplitParagraphCommand(position);
        this.cursor.moveTo(command.execute(wasm));
        this.cursor.resetPreferredX();
      }
    }
    return this.cursor.getPosition();
  }});
}'''
LIB_ANCHOR = '        .setup(|app| {\n'
MAIN_BUILDER = '''            #[cfg(windows)]
            {
                // Build from the complete merged main config, including window-state options.
                let config = app.config().app.windows.iter()
                    .find(|config| config.label == "main")
                    .ok_or("main 창 설정이 없습니다")?.clone();
                tauri::WebviewWindowBuilder::from_config(app, &config)?
                    .enable_clipboard_access()
                    .build()?;
            }
'''
WINDOWS_ANCHOR = '    let builder = builder.zoom_hotkeys_enabled(true);'
WINDOWS_BUILDER = '    let builder = builder.zoom_hotkeys_enabled(true).enable_clipboard_access();'


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _validate_predecessor(source: Path, proof: dict, pins: dict, prefix: str) -> None:
    if (not isinstance(proof, dict) or set(proof) != {'beforeSha256', 'afterSha256'}
            or proof['beforeSha256'] != pins
            or not isinstance(proof['afterSha256'], dict)
            or set(proof['afterSha256']) != set(pins)
            or any(proof['afterSha256'][name] != digest((source/(prefix+name)).read_bytes())
                   for name in pins)):
        raise ValueError('Menu clipboard requires the current clipboard, image and font proofs')


def apply(source: Path, clipboard_proof: dict, image_proof: dict, font_proof: dict) -> dict:
    """Validate every input and replacement before writing any file or proof."""
    from prepare_upstream import (ASYNC_CLIPBOARD_SOURCE_SHA256,
                                  IMAGE_INSERTION_SOURCE_SHA256, ASYNC_FONT_SOURCE_SHA256)
    for proof, pins, prefix in (
            (clipboard_proof, ASYNC_CLIPBOARD_SOURCE_SHA256, ENGINE),
            (image_proof, IMAGE_INSERTION_SOURCE_SHA256, 'third_party/rhwp/rhwp-studio/src/'),
            (font_proof, ASYNC_FONT_SOURCE_SHA256, '')):
        _validate_predecessor(source, proof, pins, prefix)
    original = {name: (source/name).read_bytes() for name in SOURCE_FILES}
    if any(digest(original[name]) != expected for name, expected in INPUT_SOURCE_SHA256.items()):
        raise ValueError('Reviewed menu clipboard source changed')
    if any(digest(original[name]) not in (expected, INPUT_NATIVE_CRLF_SHA256[name]) for name, expected in INPUT_NATIVE_SHA256.items()
           if name != LIB):
        raise ValueError('Reviewed menu clipboard native source changed')
    lib_input = digest(original[LIB])
    if lib_input not in (INPUT_NATIVE_SHA256[LIB], INPUT_NATIVE_CRLF_SHA256[LIB],
                         LIB_HWPX_INPUT_SHA256, LIB_HWPX_CRLF_INPUT_SHA256):
        raise ValueError('Reviewed menu clipboard native source changed')
    phase = 'hwpx' if lib_input in (LIB_HWPX_INPUT_SHA256, LIB_HWPX_CRLF_INPUT_SHA256) else 'prepared'
    if (source/HELPER).exists():
        raise ValueError('Menu clipboard helper already exists')
    # Only the exact reviewed Windows writer variants above may normalize to LF.
    prepared = {name: data.decode('utf-8').replace('\r\n', '\n') for name, data in original.items()}
    prepared[HANDLER] = replace_once(prepared[HANDLER], HANDLER_IMPORT,
        HANDLER_IMPORT + "\nimport { performMenuPaste } from './opengeul-menu-clipboard';")
    prepared[HANDLER] = replace_once(prepared[HANDLER], OLD_MENU_PASTE, NEW_MENU_PASTE)
    prepared[KEYBOARD] = replace_once(prepared[KEYBOARD], OLD_PLAIN_PASTE, NEW_PLAIN_PASTE)
    prepared[LIB] = replace_once(prepared[LIB], LIB_ANCHOR, LIB_ANCHOR + MAIN_BUILDER)
    prepared[WINDOWS] = replace_once(prepared[WINDOWS], WINDOWS_ANCHOR, WINDOWS_BUILDER)
    config = json.loads(prepared[CONFIG])
    windows = config.get('app', {}).get('windows', [])
    main = [window for window in windows if window.get('label') == 'main']
    if len(main) != 1 or main[0].get('create', True) is not True:
        raise ValueError('Reviewed main window clipboard configuration changed')
    main[0]['create'] = False
    prepared[CONFIG] = json.dumps(config, ensure_ascii=False, indent=2) + '\n'
    helper = (ROOT/'overlay/menu-clipboard.ts').read_bytes()
    if {name: digest(value.encode('utf-8')) for name, value in prepared.items()} != PHASE_SOURCE_SHA256[phase]:
        raise ValueError('Reviewed menu clipboard output changed')
    # All bytes and anchors are checked before the first product write.
    for name, value in prepared.items():
        (source/name).write_text(value, encoding='utf-8', newline='\n')
    (source/HELPER).write_bytes(helper)
    after = {name: digest((source/name).read_bytes()) for name in SOURCE_FILES}
    clipboard_proof['afterSha256'].update({name: after[ENGINE+name]
                                         for name in ASYNC_CLIPBOARD_SOURCE_SHA256})
    image_proof['afterSha256']['engine/input-handler.ts'] = after[HANDLER]
    font_proof['afterSha256'].update({name: after[name] for name in INPUT_SOURCE_SHA256})
    return {'beforeSha256': {name: digest(data) for name, data in original.items()},
            'afterSha256': after, 'helperSha256': digest(helper),
            'hwpxPatcherSha256': digest((ROOT/'scripts/prepare_hwpx.py').read_bytes()) if phase == 'hwpx' else None}


def validate(source: Path, proof: dict) -> None:
    helpers = {name: digest((ROOT/name).read_bytes()) for name in
               ('overlay/menu-clipboard.ts', 'scripts/prepare_hwpx.py')}
    files = {name: digest((source/name).read_bytes()) for name in (*SOURCE_FILES, HELPER)}
    validate_contract(proof, files, helpers, final=False)


def validate_contract(proof: dict, prepared_files: dict, helpers: dict, *, final: bool = True) -> None:
    """Validate copied source bytes against reviewed outputs, including coordinated forgeries."""
    if not isinstance(prepared_files, dict) or not isinstance(helpers, dict):
        raise ValueError('Incomplete menu clipboard contract inputs')
    if not isinstance(proof, dict) or set(proof) != {'beforeSha256', 'afterSha256', 'helperSha256', 'hwpxPatcherSha256'}:
        raise ValueError('Incomplete menu clipboard source proof')
    for key in ('beforeSha256', 'afterSha256'):
        values = proof[key]
        if (not isinstance(values, dict) or set(values) != set(SOURCE_FILES)
                or any(not isinstance(value, str) or not SHA.fullmatch(value) for value in values.values())):
            raise ValueError('Incomplete menu clipboard source proof')
    if any(proof['beforeSha256'][name] != expected for name, expected in INPUT_SOURCE_SHA256.items()):
        raise ValueError('Menu clipboard reviewed source proof mismatch')
    if (any(proof['beforeSha256'][name] not in (expected, INPUT_NATIVE_CRLF_SHA256[name]) for name, expected in INPUT_NATIVE_SHA256.items() if name != LIB)
            or proof['beforeSha256'][LIB] not in (INPUT_NATIVE_SHA256[LIB], INPUT_NATIVE_CRLF_SHA256[LIB],
                                                LIB_HWPX_INPUT_SHA256, LIB_HWPX_CRLF_INPUT_SHA256)):
        raise ValueError('Menu clipboard reviewed native proof mismatch')
    phase = next((name for name, values in PHASE_SOURCE_SHA256.items()
                  if proof['afterSha256'] == values), None)
    if phase is None or (final and not phase.startswith('hwpx')):
        raise ValueError('Menu clipboard reviewed output proof mismatch')
    if any(proof['afterSha256'][name] != prepared_files.get(name) for name in SOURCE_FILES):
        raise ValueError('Menu clipboard prepared source proof mismatch')
    helper = helpers.get('overlay/menu-clipboard.ts')
    if (not isinstance(helper, str) or not SHA.fullmatch(helper)
            or proof['helperSha256'] != helper or prepared_files.get(HELPER) != helper):
        raise ValueError('Menu clipboard helper proof mismatch')
    patcher = helpers.get('scripts/prepare_hwpx.py')
    if phase.startswith('hwpx'):
        if not isinstance(patcher, str) or not SHA.fullmatch(patcher) or proof['hwpxPatcherSha256'] != patcher:
            raise ValueError('Menu clipboard HWPX patcher proof mismatch')
    elif proof['hwpxPatcherSha256'] is not None:
        raise ValueError('Menu clipboard premature HWPX patcher proof')


def refresh_hwpx_lib(source: Path, proof: dict) -> None:
    """Accept only the reviewed subsequent HWPX handler registrations in native lib."""
    helpers = {name: digest((ROOT/name).read_bytes()) for name in
               ('overlay/menu-clipboard.ts', 'scripts/prepare_hwpx.py')}
    files = {name: digest((source/name).read_bytes()) for name in (*SOURCE_FILES, HELPER)}
    old_files = {**files, LIB: PHASE_SOURCE_SHA256['prepared'][LIB]}
    validate_contract(proof, old_files, helpers, final=False)
    phase = next((name for name in ('hwpx', 'hwpx-windows')
                  if files == {**PHASE_SOURCE_SHA256[name], HELPER: helpers['overlay/menu-clipboard.ts']}), None)
    if proof['afterSha256'] != PHASE_SOURCE_SHA256['prepared'] or phase is None:
        raise ValueError('Unreviewed HWPX clipboard native transform')
    updated = {**proof, 'afterSha256': dict(PHASE_SOURCE_SHA256[phase]),
               'hwpxPatcherSha256': helpers['scripts/prepare_hwpx.py']}
    validate_contract(updated, files, helpers)
    proof.update(updated)
