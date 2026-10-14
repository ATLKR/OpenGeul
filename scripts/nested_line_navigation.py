"""Bind nested Home/End to exact native visual lines and logical owner spans.

Two reviewed source modules are transformed. Native annotated rows distinguish
synthetic guide overlays and bind source offsets (including inline object slots)
to the exact scalar model text; native paint line groups retain endpoint geometry.
No paragraph-end fallback, WASM change, history mutation or cache is introduced.
"""
from __future__ import annotations
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HELPER = 'scripts/nested_line_navigation.py'
CURSOR = 'third_party/rhwp/rhwp-studio/src/engine/cursor.ts'
BRIDGE = 'third_party/rhwp/rhwp-studio/src/core/wasm-bridge.ts'
SOURCE_FILES = (CURSOR, BRIDGE)
INPUT_SHA256 = '42e7aaaea9e4d0da0be8dee9c419c11aa0e241e410e41afc1bc148caa2b28d97'
OUTPUT_SHA256 = '13d1c0d42fb80a54b2979e3ce98200eea5dd26afacd7a62eb809c3008e93fb20'
INPUT_SOURCE_SHA256 = {CURSOR: INPUT_SHA256, BRIDGE: 'f50c0ed04e6bf0953b6f41140ffb9d00a874550c8453894314fc865828e93c8e'}
OUTPUT_SOURCE_SHA256 = {CURSOR: OUTPUT_SHA256, BRIDGE: 'd16842afa5e37f673d587614c7b02094bb8f082280d347152ec8cf0b522f23a3'}
REPLACEMENTS = (
    ("import type { DocumentPosition, CursorRect, LineInfo, CellPathEntry, NavContextEntry, CellBbox } from '@/core/types';",
     "import type { DocumentPosition, CursorRect, LineInfo, CellPathEntry, NavContextEntry, CellBbox, LayerNode, LayerTextRunOp } from '@/core/types';"),
    ('        const prevLineInfo = this.isInCell()\n          ? this.wasm.getLineInfoInCell(\n              pos.sectionIndex, pos.parentParaIndex!, pos.controlIndex!,\n              pos.cellIndex!, pos.cellParaIndex!, pos.charOffset - 1)\n          : this.wasm.getLineInfo(pos.sectionIndex, pos.paragraphIndex, pos.charOffset - 1);',
     '        const prevLineInfo = this.getLineInfoForOffset(pos, pos.charOffset - 1);'),
    ('  /** 현재 커서 위치의 줄 정보를 얻는다 (본문/셀 자동 분기) */',
     "  /** Native paint textLine groups preserve the complete nested owner and line.\n   * No flat-cell or paragraph-end fallback: absent exact layout leaves navigation\n   * unchanged through the existing Home/End error boundary. Nothing is cached\n   * across document, history, font or layout changes. */\n  private getNestedVisualLines(pos: DocumentPosition): {\n    charStart: number; charEnd: number; startRect: CursorRect; endRect: CursorRect;\n  }[] {\n    const path = pos.cellPath;\n    if (!path || path.length < 2 || pos.parentParaIndex === undefined) {\n      throw new Error('Exact nested cell path required');\n    }\n    const sec = pos.sectionIndex, ppi = pos.parentParaIndex;\n    const pathJson = JSON.stringify(path);\n    const paraLength = this.wasm.getCellParagraphLengthByPath(sec, ppi, pathJson);\n    const chars = Array.from(this.wasm.getTextInCellByPath(sec, ppi, pathJson, 0, paraLength));\n    const firstPage = this.wasm.getCursorRectByPath(sec, ppi, pathJson, 0).pageIndex;\n    const lastPage = this.wasm.getCursorRectByPath(sec, ppi, pathJson, paraLength).pageIndex;\n    type Run = { start: number; op: LayerTextRunOp };\n    const lines: { charStart: number; charEnd: number; startRect: CursorRect; endRect: CursorRect }[] = [];\n    const sourceRuns = [];\n    for (let page = Math.min(firstPage, lastPage); page <= Math.max(firstPage, lastPage); page++) {\n      for (const run of this.wasm.getPageTextLayout(page).runs) {\n        if (run.secIdx !== sec || run.paraIdx !== path[path.length - 1].cellParaIndex\n            || run.parentParaIdx !== ppi || !Number.isSafeInteger(run.charStart)\n            || run.cellPath?.length !== path.length || run.cellPath.some((entry, i) =>\n              entry.controlIndex !== path[i].controlIndex || entry.cellIndex !== path[i].cellIndex\n              || entry.cellParaIndex !== path[i].cellParaIndex)) continue;\n        sourceRuns.push({ ...run, page, sourceStart: run.charStart!, logicalStart: 0 });\n      }\n    }\n    const textSpans = sourceRuns.filter(run => run.text.length > 0);\n    const editableRuns = sourceRuns.filter(run => run.text.length > 0 || !textSpans.some(span =>\n      span.sourceStart <= run.sourceStart && run.sourceStart < span.sourceStart + Array.from(span.text).length));\n    editableRuns.sort((a, b) => a.sourceStart - b.sourceStart);\n    let sourceEnd = 0, logicalEnd = 0;\n    for (const run of editableRuns) {\n      // Native layout source coordinates may include inline-object slots. The\n      // editable model uses scalar text offsets; exact full paragraph equality\n      // below binds every source-backed span to those logical coordinates.\n      if (run.sourceStart < sourceEnd) throw new Error('Overlapping native nested source spans');\n      const gap = run.sourceStart - sourceEnd;\n      for (let i = 0; i < gap && chars[logicalEnd] === '\\n'; i++) logicalEnd++;\n      run.logicalStart = logicalEnd;\n      const length = Array.from(run.text).length;\n      if (chars.slice(logicalEnd, logicalEnd + length).join('') !== run.text) {\n        throw new Error('Native nested source text differs from its logical span');\n      }\n      sourceEnd = run.sourceStart + length; logicalEnd += length;\n    }\n    if (logicalEnd !== paraLength) {\n      throw new Error('Native nested source spans differ from exact logical paragraph');\n    }\n    for (let page = Math.min(firstPage, lastPage); page <= Math.max(firstPage, lastPage); page++) {\n      const logicalRuns = editableRuns.filter(run => run.page === page);\n      const groups = new Map<LayerNode, Run[]>();\n      const visit = (node: LayerNode, line: LayerNode | null): void => {\n        if (node.kind === 'group') {\n          const currentLine = node.groupKind?.kind === 'textLine' ? node : line;\n          for (const child of node.children) visit(child, currentLine);\n        } else if (node.kind === 'clipRect') {\n          visit(node.child, line);\n        } else {\n          for (const op of node.ops) {\n            if (op.type !== 'textRun') continue;\n            // Native source keys use Unicode scalar offsets and full cell paths.\n            const key = (op as LayerTextRunOp & { source?: { stableSourceKey?: string } }).source?.stableSourceKey;\n            const match = key?.match(/^section:(\\d+)\\/para:(\\d+)\\/char:(\\d+)\\/cell:(\\d+):(.+)$/);\n            if (!match || Number(match[1]) !== sec || Number(match[2]) !== path[path.length - 1].cellParaIndex\n                || Number(match[4]) !== ppi) continue;\n            const segments = match[5].split('.').map(segment => segment.split(':').map(Number));\n            if (segments.length !== path.length || segments.some((segment, i) =>\n                segment.length !== 4 || segment.some(value => !Number.isSafeInteger(value))\n                || segment[0] !== path[i].controlIndex || segment[1] !== path[i].cellIndex\n                || segment[2] !== path[i].cellParaIndex)) continue;\n            // Paint source keys default missing charStart to zero for guide overlays.\n            // Native logical rows retain the distinction. Match rounded native bounds,\n            // not color/text heuristics; each source-backed row is consumed only once.\n            const logicalIndex = logicalRuns.findIndex(run =>\n              run.sourceStart === Number(match[3]) && run.text === op.text\n              && Math.abs(run.x - op.bbox.x) <= 0.051\n              && Math.abs(run.y - op.bbox.y) <= 0.051\n              && Math.abs(run.h - op.bbox.height) <= 0.051\n              && Math.abs(run.w - op.bbox.width) <= 0.051\n              && run.charX.length === op.positions?.length\n              && run.charX.every((x, i) => Math.abs(x - op.positions![i]) <= 0.051));\n            if (logicalIndex < 0) continue;\n            const logicalRun = logicalRuns.splice(logicalIndex, 1)[0];\n            if (!line || op.isVertical) throw new Error('Exact horizontal nested visual line unavailable');\n            const runs = groups.get(line) ?? [];\n            runs.push({ start: logicalRun.logicalStart, op }); groups.set(line, runs);\n          }\n        }\n      };\n      visit(this.wasm.getPageLayerTreeObject(page).root, null);\n      for (const runs of groups.values()) {\n        runs.sort((a, b) => a.start - b.start);\n        const charStart = runs[0].start;\n        let charEnd = charStart;\n        for (const run of runs) {\n          if (!Number.isSafeInteger(run.start) || run.start !== charEnd) {\n            throw new Error('Nested visual line contains a gap or overlapping scalar span');\n          }\n          charEnd += Array.from(run.op.text).length;\n        }\n        if (chars[charEnd - 1] === '\\n') charEnd--;\n        const rectAt = (offset: number, atEnd: boolean): CursorRect => {\n          const run = (atEnd ? [...runs].reverse() : runs).find(run =>\n            run.start <= offset && offset <= run.start + Array.from(run.op.text).length);\n          if (!run) throw new Error('Nested line has no exact endpoint span');\n          const x = run.op.positions?.[offset - run.start];\n          const bbox = run.op.bbox;\n          if (x === undefined || ![x, bbox.x, bbox.y, bbox.height].every(Number.isFinite) || bbox.height <= 0) {\n            throw new Error('Nested line has no exact endpoint geometry');\n          }\n          return { pageIndex: page, x: bbox.x + x, y: bbox.y, height: bbox.height };\n        };\n        if (charStart < 0 || charEnd < charStart || charEnd > paraLength) {\n          throw new Error('Nested line scalar range differs from its paragraph');\n        }\n        lines.push({ charStart, charEnd, startRect: rectAt(charStart, false), endRect: rectAt(charEnd, true) });\n      }\n    }\n    lines.sort((a, b) => a.charStart - b.charStart);\n    if (!lines.length || lines[0].charStart !== 0 || lines[lines.length - 1].charEnd !== paraLength\n        || lines.some((line, i) => i > 0 && (line.charStart <= lines[i - 1].charStart\n          || (line.charStart !== lines[i - 1].charEnd\n            && !(line.charStart === lines[i - 1].charEnd + 1 && chars[lines[i - 1].charEnd] === '\\n'))))) {\n      throw new Error('Complete exact nested visual lines unavailable');\n    }\n    return lines;\n  }\n\n  /** 현재 커서 위치의 줄 정보를 얻는다 (본문/셀 자동 분기) */"),
    ('  private getLineInfoForOffset(pos: DocumentPosition, charOffset: number): LineInfo {\n',
     '  private getLineInfoForOffset(pos: DocumentPosition, charOffset: number): LineInfo {\n    if ((pos.cellPath?.length ?? 0) > 1) {\n      const lines = this.getNestedVisualLines(pos);\n      let lineIndex = 0;\n      for (let i = 1; i < lines.length && charOffset >= lines[i].charStart; i++) lineIndex = i;\n      return { lineIndex, lineCount: lines.length, charStart: lines[lineIndex].charStart, charEnd: lines[lineIndex].charEnd };\n    }\n'),
    ('  private getCursorRectOnVisualLine(lineIndex: number, atEnd: boolean): CursorRect | null {\n    const pos = this.position;\n    try {\n',
     "  private getCursorRectOnVisualLine(lineIndex: number, atEnd: boolean): CursorRect | null {\n    const pos = this.position;\n    try {\n      if ((pos.cellPath?.length ?? 0) > 1) {\n        const line = this.getNestedVisualLines(pos)[lineIndex];\n        if (!line) throw new Error('Exact nested visual line index unavailable');\n        return atEnd ? line.endRect : line.startRect;\n      }\n"),
)
BRIDGE_REPLACEMENTS = (
    ("  getPageControlLayout(pageNum: number): { controls: import('./types').ControlLayoutItem[] } {",
     "  /** Logical source identities omit synthetic guide text; current metric context is preserved. */\n  getPageTextLayout(pageNum: number): { runs: {\n    text: string; x: number; y: number; w: number; h: number; charX: number[];\n    secIdx?: number; paraIdx?: number; charStart?: number;\n    parentParaIdx?: number; cellPath?: CellPathEntry[];\n  }[] } {\n    if (!this.doc) throw new Error('문서가 로드되지 않았습니다');\n    return JSON.parse(this.doc.getPageTextLayout(pageNum));\n  }\n\n  getPageControlLayout(pageNum: number): { controls: import('./types').ControlLayoutItem[] } {"),
)


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def transformed_source(name: str, data: bytes) -> bytes:
    if name not in SOURCE_FILES or digest(data) != INPUT_SOURCE_SHA256[name]:
        raise ValueError('Nested navigation reviewed source input changed')
    source = data.decode('utf-8')
    replacements = REPLACEMENTS if name == CURSOR else BRIDGE_REPLACEMENTS
    for old, new in replacements:
        if source.count(old) != 1:
            raise ValueError('Nested navigation requires exact reviewed source anchors')
        source = source.replace(old, new)
    output = source.encode('utf-8')
    if digest(output) != OUTPUT_SOURCE_SHA256[name]:
        raise ValueError('Nested navigation reviewed source output changed')
    return output


def transformed(data: bytes) -> bytes:
    return transformed_source(CURSOR, data)


def apply(source: Path) -> dict:
    outputs = {}
    for name in SOURCE_FILES:
        path = source / name
        if path.is_symlink() or not path.is_file():
            raise ValueError('Nested navigation requires regular reviewed sources')
        outputs[name] = transformed_source(name, path.read_bytes())
    proof = {'beforeSha256': dict(INPUT_SOURCE_SHA256),
             'afterSha256': dict(OUTPUT_SOURCE_SHA256),
             'helperSha256': digest((ROOT / HELPER).read_bytes())}
    validate_contract(proof, {name: digest(data) for name, data in outputs.items()},
                      {HELPER: proof['helperSha256']})
    for name, data in outputs.items():
        (source / name).write_bytes(data)
    return proof


def validate_contract(proof: dict, prepared_files: dict, helpers: dict) -> None:
    if not isinstance(proof, dict) or set(proof) != {'beforeSha256', 'afterSha256', 'helperSha256'}:
        raise ValueError('Incomplete nested navigation proof')
    if proof['beforeSha256'] != INPUT_SOURCE_SHA256 or proof['afterSha256'] != OUTPUT_SOURCE_SHA256:
        raise ValueError('Nested navigation reviewed source proof mismatch')
    if not isinstance(prepared_files, dict) or any(
            prepared_files.get(name) != digest for name, digest in OUTPUT_SOURCE_SHA256.items()):
        raise ValueError('Nested navigation prepared source mismatch')
    expected = helpers.get(HELPER) if isinstance(helpers, dict) else None
    if expected != digest((ROOT / HELPER).read_bytes()) or proof['helperSha256'] != expected:
        raise ValueError('Nested navigation helper proof mismatch')
