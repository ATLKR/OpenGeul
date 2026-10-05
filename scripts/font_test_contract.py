"""Separate generic loader unit fixtures from OpenGeul's installed-only runtime policy."""
from pathlib import Path
import sys
from buildkit import ROOT, replace_once

def prepare(source: Path) -> None:
    core=source/'apps/studio-host/src/core'
    catalog=core/'font-catalog.ts'
    fixture=core/'font-catalog.test-fixture.ts'
    if fixture.exists():raise ValueError('Refusing to replace an existing fixture')
    fixture.write_bytes(catalog.read_bytes())
    test=core/'font-loader.test.ts'
    original=test.read_text(encoding='utf-8')
    anchor="import { beforeEach, describe, expect, it, vi } from 'vitest';"
    test.write_text(replace_once(original,anchor,anchor+"\n// Explicit fixture for generic bundled-loader behavior; production catalog has its own tests.\nvi.mock('./font-catalog', () => import('./font-catalog.test-fixture'));"),encoding='utf-8')
    target=core/'opengeul-installed-fonts.test.ts'
    target.write_bytes((ROOT/'overlay/installed-fonts.test.ts').read_bytes())
    print('Preserved all 7 generic font-loader tests with an explicit fixture; added installed-only runtime tests.')
if __name__=='__main__':prepare(Path(sys.argv[1]))
