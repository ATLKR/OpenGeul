"""Exact HOP 0.5.3 adapter compatibility for rhwp 0.9.1 renderer candidates."""
from pathlib import Path
import hashlib
import stat
ROOT=Path(__file__).resolve().parents[1]
HELPER='scripts/renderer_font_candidates.py'
SOURCE_FILES = ('apps/studio-host/src/core/local-fonts.ts',
 'apps/studio-host/src/core/desktop-local-fonts.ts',
 'third_party/rhwp/rhwp-studio/src/core/local-fonts.ts',
 'apps/studio-host/src/upstream/local-fonts.ts',
 'apps/studio-host/tsconfig.json')
INPUT_SOURCE_SHA256 = {'apps/studio-host/src/core/local-fonts.ts': '3b91132a53e1e5fa5c22a45d6a68ca515d3b5a1bd97457caed32421ec3efda0b',
 'apps/studio-host/src/core/desktop-local-fonts.ts': 'c944a85a21e91d17bb8df9cdc3d4e4b9a3740ae2948969808044b890c87088be',
 'third_party/rhwp/rhwp-studio/src/core/local-fonts.ts': '31afb48f00f66dc76ebea9b2e089489da572e65a73be3e5cbe786f16debff8cd',
 'apps/studio-host/src/upstream/local-fonts.ts': 'bb4d41f130d11c7e16004c2d8d5c1f7fa9da784a9f7343037d51723e78a1235c',
 'apps/studio-host/tsconfig.json': '23846e3a3bd66787e1852700ff3711977c411ad07c602dfa4ff77b9145157a97'}
OUTPUT_SOURCE_SHA256 = {'apps/studio-host/src/core/local-fonts.ts': '57a81b782ec5fc68fe89cf336d1b82b240654efec695d7bbf6012deaad3b460c',
 'apps/studio-host/src/core/desktop-local-fonts.ts': '62d0ee7b9d94a69e18009a236a0d782456c46d5d82ccb6b746d2ebf7d9b777a4',
 'third_party/rhwp/rhwp-studio/src/core/local-fonts.ts': '31afb48f00f66dc76ebea9b2e089489da572e65a73be3e5cbe786f16debff8cd',
 'apps/studio-host/src/upstream/local-fonts.ts': 'bb4d41f130d11c7e16004c2d8d5c1f7fa9da784a9f7343037d51723e78a1235c',
 'apps/studio-host/tsconfig.json': '23846e3a3bd66787e1852700ff3711977c411ad07c602dfa4ff77b9145157a97'}
REPLACEMENTS = {'apps/studio-host/src/core/local-fonts.ts': (('  resolveDesktopFont,\n',
                                               '  resolveDesktopFont,\n'
                                               '  resolveDesktopFontCandidates,\n'),
                                              ('export async function '
                                               'loadRendererLocalFont(record: LocalFontRecord): '
                                               'Promise<HostFontData | null> {',
                                               '/** Preserve upstream split-program selection and '
                                               'the existing desktop read boundary. */\n'
                                               'export function '
                                               'resolveRendererLocalFontCandidates(name: string, '
                                               'style: LocalFontStyleRequest): LocalFontRecord[] '
                                               '{\n'
                                               '  return isDesktopTauriRuntime() && '
                                               '!hasHostFontProvider()\n'
                                               '    ? resolveDesktopFontCandidates(name, style)\n'
                                               '    : '
                                               'upstreamLocalFonts.resolveRendererLocalFontCandidates(name, '
                                               'style);\n'
                                               '}\n'
                                               '\n'
                                               'export async function '
                                               'loadRendererLocalFont(record: LocalFontRecord): '
                                               'Promise<HostFontData | null> {')),
 'apps/studio-host/src/core/desktop-local-fonts.ts': (('  LocalFontRecord,\n',
                                                       '  LocalFontRecord,\n'
                                                       '  LocalFontStyleRequest,\n'),
                                                      ('export async function '
                                                       'loadDesktopFontBytesFor(\n',
                                                       '/** Renderer candidates use only the '
                                                       'catalog already authorized by the native '
                                                       'bridge. */\n'
                                                       'export function '
                                                       'resolveDesktopFontCandidates(fontName: '
                                                       'string, style: LocalFontStyleRequest): '
                                                       'LocalFontRecord[] {\n'
                                                       '  const target = '
                                                       'normalizeFontName(fontName);\n'
                                                       '  const entries = cachedFontEntries ?? '
                                                       '[];\n'
                                                       '  // Family aliases may describe the same '
                                                       'existing byte-loader reference. This\n'
                                                       '  // proves whole-file/faceIndex-0 read '
                                                       'equivalence, not native collection faces.\n'
                                                       '  const sameReadIdentity = (aliases: '
                                                       'LocalFontEntry[]) => {\n'
                                                       '    const first = aliases[0];\n'
                                                       '    if (!first?.path || !first.path.trim() '
                                                       "|| typeof first.weight !== 'number' || "
                                                       '!Number.isFinite(first.weight)) return '
                                                       'false;\n'
                                                       '    const slant = '
                                                       "first.style.toLocaleLowerCase('en-US');\n"
                                                       "    if (!['normal', 'italic', "
                                                       "'oblique'].includes(slant)\n"
                                                       "      || !['system-installed', "
                                                       "'file-backed'].includes(first.sourceKind)) "
                                                       'return false;\n'
                                                       '    const ps = '
                                                       'normalizeFontName(first.postScriptName);\n'
                                                       '    return !!ps && aliases.every((entry) '
                                                       '=> entry.path === first.path\n'
                                                       '      && '
                                                       'normalizeFontName(entry.postScriptName) '
                                                       '=== ps && entry.weight === first.weight\n'
                                                       '      && '
                                                       "entry.style.toLocaleLowerCase('en-US') === "
                                                       'slant && entry.sourceKind === '
                                                       'first.sourceKind);\n'
                                                       '  };\n'
                                                       '  const explicit = entries.filter((entry) '
                                                       '=> normalizeFontName(entry.postScriptName) '
                                                       '=== target);\n'
                                                       '  if (explicit.length) return '
                                                       'explicit.length === 1 || '
                                                       'sameReadIdentity(explicit)\n'
                                                       '    ? [toLocalFontRecord(explicit[0])] : '
                                                       '[];\n'
                                                       '\n'
                                                       '  const family = entries.filter((entry) => '
                                                       'normalizeFontName(entry.family) === '
                                                       'target);\n'
                                                       '  const matches = (entry: LocalFontEntry, '
                                                       'slant: string) =>\n'
                                                       '    entry.weight === style.weight && '
                                                       "entry.style.toLocaleLowerCase('en-US') === "
                                                       'slant;\n'
                                                       '  const exact = family.filter((entry) => '
                                                       'matches(entry, style.slant));\n'
                                                       '  const alternate = style.slant === '
                                                       "'normal' ? [] : family.filter((entry) =>\n"
                                                       '    matches(entry, style.slant === '
                                                       "'italic' ? 'oblique' : 'italic'));\n"
                                                       '  const selected = exact.length ? exact : '
                                                       'alternate;\n'
                                                       '  if (!selected.length || new '
                                                       'Set(selected.map((entry) => '
                                                       'normalizeFontName(entry.family))).size !== '
                                                       '1) return [];\n'
                                                       '\n'
                                                       '  // Check every matching PS entry, since '
                                                       'the unchanged byte loader may choose\n'
                                                       "  // the catalog's first alias rather than "
                                                       'the requested localized family.\n'
                                                       '  const unique = new Map<string, '
                                                       'LocalFontEntry>();\n'
                                                       '  for (const entry of selected) {\n'
                                                       '    const id = '
                                                       'normalizeFontName(entry.postScriptName);\n'
                                                       '    const aliases = '
                                                       'entries.filter((candidate) => '
                                                       'normalizeFontName(candidate.postScriptName) '
                                                       '=== id);\n'
                                                       '    if (!id || (aliases.length > 1 && '
                                                       '!sameReadIdentity(aliases))) return [];\n'
                                                       '    if (!unique.has(id)) unique.set(id, '
                                                       'entry);\n'
                                                       '  }\n'
                                                       '  return '
                                                       '[...unique.values()].map(toLocalFontRecord);\n'
                                                       '}\n'
                                                       '\n'
                                                       'export async function '
                                                       'loadDesktopFontBytesFor(\n'))}

def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def regular(path):
    path=Path(path)
    for item in (path,*path.parents):
        if item.exists() or item.is_symlink():
            info=item.lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(info,'st_file_attributes',0)&0x400:raise ValueError('Renderer font source path alias')
    if not path.is_file():raise ValueError('Renderer font source missing')
def apply(source):
    source=Path(source);pending={}
    for name in SOURCE_FILES:
        path=source/name;regular(path);value=path.read_bytes()
        if hashlib.sha256(value).hexdigest()!=INPUT_SOURCE_SHA256[name]:raise ValueError('Renderer font candidates source drift or reapplication')
        for old,new in REPLACEMENTS.get(name,()):
            if value.count(old.encode())!=1:raise ValueError('Renderer font candidates anchor must occur once')
            value=value.replace(old.encode(),new.encode())
        if hashlib.sha256(value).hexdigest()!=OUTPUT_SOURCE_SHA256[name]:raise ValueError('Renderer font candidates output drift')
        pending[name]=value
    for name,value in pending.items():
        if name in REPLACEMENTS:(source/name).write_bytes(value)
    return {'beforeSha256':dict(INPUT_SOURCE_SHA256),'afterSha256':{n:sha(source/n)for n in SOURCE_FILES},'helperSha256':sha(ROOT/HELPER)}
def validate_contract(proof,prepared_files,helpers):
    expected={'beforeSha256':INPUT_SOURCE_SHA256,'afterSha256':OUTPUT_SOURCE_SHA256,'helperSha256':sha(ROOT/HELPER)}
    if type(proof)is not dict or set(proof)!=set(expected)or proof!=expected:raise ValueError('Exact renderer font candidates proof required')
    if type(prepared_files)is not dict or any(prepared_files.get(n)!=v for n,v in OUTPUT_SOURCE_SHA256.items()):raise ValueError('Renderer font candidates prepared source mismatch')
    if type(helpers)is not dict or helpers.get(HELPER)!=expected['helperSha256']:raise ValueError('Renderer font candidates helper mismatch')
