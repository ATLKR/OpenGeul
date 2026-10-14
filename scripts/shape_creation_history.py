"""Record public shape placement in the existing real snapshot/history router.

This transform consumes the byte-pinned final menu/clipboard InputHandler and
preserves placement geometry and object selection. Creation becomes one atomic
undo step; pending placement belongs to its original document/handler lifecycle.
No upstream files are changed in this repository.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HELPER = 'scripts/shape_creation_history.py'
HANDLER = 'third_party/rhwp/rhwp-studio/src/engine/input-handler.ts'
CONNECTOR = 'third_party/rhwp/rhwp-studio/src/engine/input-handler-connector.ts'
SOURCE_FILES = (HANDLER, CONNECTOR)
INPUT_SHA256 = 'ee144804d21ea5585fc03e5057317310990197c3b096c9aa34caa8006299d3c8'
OUTPUT_SHA256 = 'bd3e440d6c71f268d58018d5ed84a6f1622d5f15264b267fcd40f5933c51aaac'
CONNECTOR_INPUT_SHA256 = 'ec265208f6fa7bd4bb82368c8a611c4915a0be89d9acb99108fad911f12a4dec'
CONNECTOR_OUTPUT_SHA256 = '61bdad87ff678d8279ec8103aa54a2c6aa7d238006bff7e30a92bef5f101e2e0'
OLD = '''      const result = this.wasm.createShapeControl({
        sectionIdx: sec,
        paraIdx,
        charOffset,
        width: wHwp,
        height: hHwp,
        horzOffset,
        vertOffset,
        shapeType: this.shapePlacementType,
        lineFlipX,
        lineFlipY,
        ...(isTextbox ? { treatAsChar: false, textWrap: 'InFrontOfText' } : {}),
      });
      if (result.ok) {
        this.eventBus.emit('document-changed');'''
NEW = '''      let result: { ok: boolean; paraIdx: number; controlIdx: number } | undefined;
      this.executeOperation({
        kind: 'snapshot',
        operationType: 'insertShape',
        operation: (wasm: WasmBridge) => {
          result = wasm.createShapeControl({
            sectionIdx: sec,
            paraIdx,
            charOffset,
            width: wHwp,
            height: hHwp,
            horzOffset,
            vertOffset,
            shapeType: this.shapePlacementType,
            lineFlipX,
            lineFlipY,
            ...(isTextbox ? { treatAsChar: false, textWrap: 'InFrontOfText' } : {}),
          });
          // A rejected creation must not commit history or leave partial state.
          if (!result.ok) throw new Error('[InputHandler] shape creation rejected');
          return cursorPos;
        },
      });
      if (result?.ok) {'''
PLACEMENT_REPLACEMENTS = (
    ("import * as _picture from './input-handler-picture';",
     "import * as _picture from './input-handler-picture';\nimport * as _connector from './input-handler-connector';", 1),
    ('  private textboxPlacementMode = false;',
     '  private textboxPlacementMode = false;\n  private shapePlacementContext: { isCurrent(): boolean } | null = null;', 1),
    ("    this.shapePlacementType = 'textbox';\n    this.textboxPlacementMode = true;",
     "    const context = this.captureImageInsertionContext();\n    if (!context.isCurrent()) return;\n    this.cancelShapePlacement();\n    this.shapePlacementContext = context;\n    this.shapePlacementType = 'textbox';\n    this.textboxPlacementMode = true;", 1),
    ('''  enterShapePlacementMode(shapeType: string): void {
    this.shapePlacementType = shapeType;''',
     '''  enterShapePlacementMode(shapeType: string): void {
    const context = this.captureImageInsertionContext();
    if (!context.isCurrent()) return;
    this.cancelShapePlacement();
    this.shapePlacementContext = context;
    this.shapePlacementType = shapeType;''', 1),
    ('''  private cancelTextboxPlacement(): void {
    this.textboxPlacementMode = false;''',
     '''  private cancelTextboxPlacement(): void {
    if (this.textboxPlacementDrag) document.removeEventListener('mouseup', this.onMouseUpBound);
    this.shapePlacementContext = null;
    this.textboxPlacementMode = false;''', 1),
    ('''  private finishTextboxPlacement(e: MouseEvent): void {
    const drag = this.textboxPlacementDrag;''',
     '''  private finishTextboxPlacement(e: MouseEvent): void {
    if (!this.shapePlacementContext?.isCurrent()) {
      this.cancelTextboxPlacement();
      return;
    }
    const drag = this.textboxPlacementDrag;''', 1),
    ('''    // 모드 종료
    this.textboxPlacementMode = false;
    this.textboxPlacementDrag = null;
    this.container.style.cursor = '';
  }

  /** 표 객체''',
     '''    // 모드 종료
    this.cancelTextboxPlacement();
  }

  /** 표 객체''', 1),
    ('''    this.imageInsertionLifecycle++;
    if (this.imagePlacementMode || this.imagePlacementData || this.imagePlacementDrag || this.imagePlacementOverlay) {''',
     '''    this.imageInsertionLifecycle++;
    if (this.textboxPlacementMode || this.shapePlacementContext || this.textboxPlacementDrag || this.textboxPlacementOverlay || this.polygonDrawingMode || this.connectorDrawingMode) {
      this.cancelShapePlacement();
    }
    if (this.imagePlacementMode || this.imagePlacementData || this.imagePlacementDrag || this.imagePlacementOverlay) {''', 2),
    ('''  /** 글상자 배치 모드 취소 */
  private cancelTextboxPlacement(): void {''',
     '''  /** Cancel every shape placement path before reuse or handler teardown. */
  private cancelShapePlacement(): void {
    this.cancelTextboxPlacement();
    this.cancelPolygonDrawing();
    _connector.exitConnectorDrawingMode.call(this);
  }

  /** 글상자 배치 모드 취소 */
  private cancelTextboxPlacement(): void {''', 1),
    ('''  private finishPolygonDrawing(): void {
    const pts = this.polygonPoints;''',
     '''  private finishPolygonDrawing(): void {
    if (!this.shapePlacementContext?.isCurrent()) {
      this.cancelPolygonDrawing();
      return;
    }
    const pts = this.polygonPoints;''', 1),
    ('''  private cancelPolygonDrawing(): void {
    this.polygonDrawingMode = false;''',
     '''  private cancelPolygonDrawing(): void {
    this.shapePlacementContext = null;
    this.polygonDrawingMode = false;''', 1),
)
POLYGON_OLD = '''      const result = this.wasm.createShapeControl({
        sectionIdx: sec,
        paraIdx,
        charOffset,
        width: wHwp || 2250,
        height: hHwp || 2250,
        horzOffset,
        vertOffset,
        shapeType: 'polygon',
        polygonPoints: pointsHwp,
      });
      if (result.ok) {
        this.eventBus.emit('document-changed');'''
POLYGON_NEW = '''      let result: { ok: boolean; paraIdx: number; controlIdx: number } | undefined;
      this.executeOperation({
        kind: 'snapshot',
        operationType: 'insertPolygon',
        operation: (wasm: WasmBridge) => {
          result = wasm.createShapeControl({
            sectionIdx: sec,
            paraIdx,
            charOffset,
            width: wHwp || 2250,
            height: hHwp || 2250,
            horzOffset,
            vertOffset,
            shapeType: 'polygon',
            polygonPoints: pointsHwp,
          });
          if (!result.ok) throw new Error('[InputHandler] polygon creation rejected');
          return cursorPos;
        },
      });
      if (result?.ok) {'''
CONNECTOR_OLD = '''    const result = this.wasm.createShapeControl({
      sectionIdx: sec,
      paraIdx,
      charOffset,
      width: wHwp,
      height: hHwp,
      horzOffset,
      vertOffset,
      shapeType: connectorType,
      lineFlipX,
      lineFlipY,
      // 연결선 전용 필드
      startSubjectID: startPt.instanceId,
      startSubjectIndex: startPt.index,
      endSubjectID: endPt.instanceId,
      endSubjectIndex: endPt.index,
    });
    if (result.ok) {
      this.eventBus.emit('document-changed');'''
CONNECTOR_NEW = '''    let result: { ok: boolean; paraIdx: number; controlIdx: number } | undefined;
    this.executeOperation({
      kind: 'snapshot',
      operationType: 'insertConnector',
      operation: (wasm: WasmBridge) => {
        result = wasm.createShapeControl({
          sectionIdx: sec,
          paraIdx,
          charOffset,
          width: wHwp,
          height: hHwp,
          horzOffset,
          vertOffset,
          shapeType: connectorType,
          lineFlipX,
          lineFlipY,
          // 연결선 전용 필드
          startSubjectID: startPt.instanceId,
          startSubjectIndex: startPt.index,
          endSubjectID: endPt.instanceId,
          endSubjectIndex: endPt.index,
        });
        if (!result.ok) throw new Error('[Connector] connector creation rejected');
        return pos;
      },
    });
    if (result?.ok) {'''
CONNECTOR_REPLACEMENTS = (
    ("import { isBodyControl } from './picture-hit-policy.ts';",
     "import { isBodyControl } from './picture-hit-policy.ts';\nimport type { WasmBridge } from '../core/wasm-bridge';", 1),
    ('''): void {
  removeConnectorPreview.call(this);
  removeConnectionPointOverlay.call(this);

  // SHAPE_COMPONENT''',
     '''): void {
  if (!this.shapePlacementContext?.isCurrent()) {
    exitConnectorDrawingMode.call(this);
    return;
  }
  removeConnectorPreview.call(this);
  removeConnectionPointOverlay.call(this);

  // SHAPE_COMPONENT''', 1),
    ('''export function exitConnectorDrawingMode(this: any): void {
  this.connectorDrawingMode = false;''',
     '''export function exitConnectorDrawingMode(this: any): void {
  this.shapePlacementContext = null;
  this.connectorDrawingMode = false;''', 1),
    (CONNECTOR_OLD, CONNECTOR_NEW, 1),
)
INPUT_SOURCE_SHA256 = {HANDLER: INPUT_SHA256, CONNECTOR: CONNECTOR_INPUT_SHA256}
OUTPUT_SOURCE_SHA256 = {HANDLER: OUTPUT_SHA256, CONNECTOR: CONNECTOR_OUTPUT_SHA256}


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def transformed(data: bytes, path: str = HANDLER) -> bytes:
    if path not in SOURCE_FILES or digest(data) != INPUT_SOURCE_SHA256[path]:
        raise ValueError('Shape history reviewed InputHandler input changed')
    source = data.decode('utf-8')
    replacements = ((*PLACEMENT_REPLACEMENTS, (OLD, NEW, 1), (POLYGON_OLD, POLYGON_NEW, 1))
                    if path == HANDLER else CONNECTOR_REPLACEMENTS)
    for old, new, count in replacements:
        if source.count(old) != count:
            raise ValueError('Shape lifecycle requires exact reviewed placement anchors')
        source = source.replace(old, new)
    output = source.encode('utf-8')
    if digest(output) != OUTPUT_SOURCE_SHA256[path]:
        raise ValueError('Shape history reviewed InputHandler output changed')
    return output


def apply(source: Path, clipboard: dict, image: dict, font: dict, menu: dict) -> dict:
    """Check current reviewed predecessor proofs and all bytes before mutation."""
    import menu_clipboard
    from prepare_upstream import (ASYNC_CLIPBOARD_SOURCE_SHA256,
        IMAGE_INSERTION_SOURCE_SHA256, ASYNC_FONT_SOURCE_SHA256)
    menu_clipboard.validate(source, menu)
    for proof, pins, prefix in (
        (clipboard, ASYNC_CLIPBOARD_SOURCE_SHA256, 'third_party/rhwp/rhwp-studio/src/engine/'),
        (image, IMAGE_INSERTION_SOURCE_SHA256, 'third_party/rhwp/rhwp-studio/src/'),
        (font, ASYNC_FONT_SOURCE_SHA256, ''),
    ):
        menu_clipboard._validate_predecessor(source, proof, pins, prefix)
    outputs = {name: transformed((source/name).read_bytes(), name) for name in SOURCE_FILES}
    proof = {'beforeSha256': dict(INPUT_SOURCE_SHA256),
             'afterSha256': dict(OUTPUT_SOURCE_SHA256),
             'helperSha256': digest((ROOT/HELPER).read_bytes())}
    validate_contract(proof, {name:digest(data) for name,data in outputs.items()}, {HELPER: proof['helperSha256']})
    for name,data in outputs.items(): (source/name).write_bytes(data)
    # Preserve all original before pins. Final after maps follow the actual
    # transformed handler and are checked against separate fixed output pins.
    clipboard['afterSha256']['input-handler.ts'] = OUTPUT_SHA256
    image['afterSha256']['engine/input-handler.ts'] = OUTPUT_SHA256
    font['afterSha256'][HANDLER] = OUTPUT_SHA256
    menu['afterSha256'][HANDLER] = OUTPUT_SHA256
    return proof


def validate_contract(proof: dict, prepared_files: dict, helpers: dict) -> None:
    if not isinstance(proof, dict) or set(proof) != {'beforeSha256','afterSha256','helperSha256'}:
        raise ValueError('Incomplete shape creation history proof')
    if proof['beforeSha256'] != INPUT_SOURCE_SHA256 or proof['afterSha256'] != OUTPUT_SOURCE_SHA256:
        raise ValueError('Shape history reviewed source proof mismatch')
    if not isinstance(prepared_files, dict) or any(prepared_files.get(name) != sha for name,sha in OUTPUT_SOURCE_SHA256.items()):
        raise ValueError('Shape history prepared source mismatch')
    expected = helpers.get(HELPER) if isinstance(helpers, dict) else None
    if expected != digest((ROOT/HELPER).read_bytes()) or proof['helperSha256'] != expected:
        raise ValueError('Shape history helper proof mismatch')
