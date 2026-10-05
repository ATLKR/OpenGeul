"""Fetch exact public upstream versions, then apply OpenGeul overlays. Never resets user files."""
from __future__ import annotations
import argparse
import json
import hashlib
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from buildkit import ROOT, FONT_EXTENSIONS, make_assets, package_version, replace_once, tauri_config


def run(*args: str, cwd: Path) -> str:
    result=subprocess.run(list(args),cwd=cwd,check=True,text=True,encoding="utf-8",stdout=subprocess.PIPE)
    return result.stdout.strip()


def replace_file(path: Path, old: str, new: str, expected: int = 1) -> None:
    path.write_text(replace_once(path.read_text(encoding='utf-8'),old,new,expected=expected),encoding='utf-8')


def patch(source: Path, version: str) -> None:
    package_version(version)
    protected = ['apps/desktop/src-tauri/src/' + x for x in ('commands.rs','state.rs','pdf_export.rs','pending_open.rs','app_quit.rs','recent_documents.rs')]
    protected += ['apps/studio-host/hop-overrides.ts']
    original = {name: hashlib.sha256((source/name).read_bytes()).hexdigest() for name in protected}
    native=source/'apps/desktop/src-tauri'
    host=source/'apps/studio-host'
    upstream=source/'third_party/rhwp'
    cfg=native/'tauri.conf.json'
    cfg.write_text(json.dumps(tauri_config(json.loads(cfg.read_text(encoding='utf-8')),version),ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    win=native/'tauri.windows.conf.json'
    w=json.loads(win.read_text(encoding='utf-8'))
    for window in w.get('app',{}).get('windows',[]): window['title']='OpenGeul'
    win.write_text(json.dumps(w,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    for rel in ('package.json','apps/desktop/package.json'):
        path=source/rel; value=json.loads(path.read_text(encoding='utf-8')); value['version']=version
        path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    replace_file(native/'Cargo.toml','version = "0.4.4"',f'version = "{version}"')
    replace_file(native/'Cargo.lock','name = "hop-desktop"\nversion = "0.4.4"',f'name = "hop-desktop"\nversion = "{version}"')
    for component in ('Preview','Thumbnail'):
        path=source/f'apps/desktop/quicklook/Resources/{component}/Info.plist'
        if path.is_file():
            value=path.read_text(encoding='utf-8'); value,n=re.subn(r'(<key>CFBundleShortVersionString</key>\s*<string>)[^<]+',lambda m:m[1]+version,value)
            if n!=1: raise ValueError('Unexpected Quick Look version metadata')
            path.write_text(value,encoding='utf-8')
    replace_file(native/'src/lib.rs','        .plugin(tauri_plugin_updater::Builder::new().build())\n','')
    replace_file(native/'src/lib.rs','mod app_quit;','mod app_quit;\nmod opengeul_font_resources;')
    replace_file(native/'src/lib.rs','tauri::generate_handler![','tauri::generate_handler![\n            opengeul_font_resources::open_font_resource,')
    shutil.copy2(ROOT/'overlay/updates.rs',native/'src/updates.rs')
    # Native font scanning remains restricted to installed system/per-user font directories.
    font=native/'src/font_catalog.rs'
    replace_file(font,'use tauri::{AppHandle, Manager};','use tauri::AppHandle;')
    replace_file(font,'''pub fn pdf_font_dirs(app: &AppHandle) -> Vec<PathBuf> {
    let mut dirs = Vec::new();
    if let Ok(resource_dir) = app.path().resource_dir() {
        dirs.push(resource_dir.join("fonts/pdf"));
    }
    dirs.extend(desktop_extra_font_dirs());
    dedupe_existing_dirs(dirs)
}''','''pub fn pdf_font_dirs(_app: &AppHandle) -> Vec<PathBuf> {
    desktop_extra_font_dirs()
}''')
    replace_file(font, '    let allowed_roots = desktop_extra_font_dirs();', '''    let mut allowed_roots = desktop_extra_font_dirs();
    #[cfg(windows)]
    if let Some(windir) = env_path("WINDIR") {
        allowed_roots.extend(dedupe_existing_dirs(vec![windir.join("Fonts")]));
    }''')
    shutil.copy2(ROOT/'overlay/font-catalog.ts',host/'src/core/font-catalog.ts')
    # Keep the Vite asset directory, but remove font programs before frontend build.
    for path in (source/'assets/fonts').rglob('*'):
        if path.is_file() and path.suffix.lower() in FONT_EXTENSIONS: path.unlink()
    make_assets(source/'assets/opengeul')
    index=host/'index.html'
    replace_file(index,'<title>HOP</title>','<title>OpenGeul</title>')
    replace_file(index,'href="/favicon.ico"','href="/opengeul.ico"')
    (host/'public').mkdir(exist_ok=True)
    shutil.copy2(source/'assets/opengeul/app.ico',host/'public/opengeul.ico')
    replace_file(index,'</body>','<script type="module" src="/src/opengeul-font-help.ts"></script>\n</body>')
    # Do not rename upstream technical identifiers or credits indiscriminately.
    windows=native/'src/windows.rs'
    content=windows.read_text(encoding='utf-8').replace('"HOP"','"OpenGeul"').replace(' — HOP',' — OpenGeul').replace(' - HOP',' - OpenGeul')
    windows.write_text(content,encoding='utf-8')
    resources=json.loads((ROOT/'config/font-resources.json').read_text(encoding='utf-8'))
    native_lines=['#[tauri::command]','pub fn open_font_resource(resource: String) -> Result<(), String> {','    let target = match resource.as_str() {']
    for item in resources: native_lines.append(f'        {json.dumps(item["id"])} => {json.dumps(item["url"])},')
    native_lines += ['        _ => return Err("허용되지 않은 글꼴 리소스입니다.".into()),','    };','    open::that(target).map_err(|error| error.to_string())','}']
    (native/'src/opengeul_font_resources.rs').write_text('\n'.join(native_lines)+'\n',encoding='utf-8')
    shutil.copy2(ROOT/'overlay/opengeul-font-help.ts',host/'src/opengeul-font-help.ts')
    (host/'src/opengeul-font-resources.ts').write_text('export default '+json.dumps(resources,ensure_ascii=False)+' as const;\n',encoding='utf-8')
    # Do not silently allow the upstream PDF backend to embed every installed font.
    pdf=upstream/'src/renderer/pdf.rs'
    value=pdf.read_text(encoding='utf-8')
    anchor='/// Native PDF implementation selected by callers such as `export-pdf`.'
    value=replace_once(value,anchor,'#[cfg(not(target_arch = "wasm32"))]\nmod opengeul_pdf_guard;\n\n'+anchor)
    value=replace_once(value,'    let fontdb = create_fontdb(export_options);','    let mut fontdb = create_fontdb(export_options);\n    opengeul_pdf_guard::enforce(&mut fontdb, svg_pages)?;')
    value=replace_once(value,'    crate::renderer::font_paths::load_into_fontdb(&mut fontdb, &options.font_paths);','    for dir in &options.font_paths { fontdb.load_fonts_dir(dir); }')
    pdf.write_text(value,encoding='utf-8')
    module_dir=upstream/'src/renderer/pdf'; module_dir.mkdir(exist_ok=True)
    shutil.copy2(ROOT/'overlay/opengeul_pdf_guard.rs',module_dir/'opengeul_pdf_guard.rs')
    shutil.copy2(ROOT/'overlay/font_policy.rs',module_dir/'opengeul_font_policy.rs')
    adapter=source/'apps/desktop/rhwp-adapter/src/lib.rs'
    text=adapter.read_text(encoding='utf-8')
    text=replace_once(text,'"Noto Sans KR".to_string()','"Malgun Gothic".to_string()',expected=3)
    adapter.write_text(text,encoding='utf-8')
    for name, digest in original.items():
        if hashlib.sha256((source/name).read_bytes()).hexdigest() != digest:
            raise ValueError('A protected upstream Windows capability was changed: '+name)
    (source/'.opengeul-overlay.json').write_text(json.dumps({'version':version,'source':'OpenGeul distribution overlays','preservedFiles':original,'changes':['branding','installed-only fonts','font help','Windows system-font read allowlist','PDF metadata guard','disabled upstream updater']},indent=2),encoding='utf-8')


def port_windows_contract_test(dest: Path) -> None:
    # Windows baseline run 37290548163 reproduced this separator-only false positive.
    replace_file(dest/'tests/rhwp-boundary.test.mjs',
                 'const relativePath = relative(studioRoot, file);',
                 "const relativePath = relative(studioRoot, file).replaceAll('\\\\', '/');")


def main() -> None:
    parser=argparse.ArgumentParser()
    parser.add_argument('--directory',type=Path,default=ROOT/'.work/hop')
    parser.add_argument('--fetch-only',action='store_true')
    parser.add_argument('--patch-only',action='store_true')
    args=parser.parse_args();dest=args.directory.resolve()
    if args.fetch_only and args.patch_only:raise ValueError('Select one preparation mode')
    lock=json.loads((ROOT/'config/upstream.lock.json').read_text(encoding='utf-8'))
    version=json.loads((ROOT/'config/product.json').read_text(encoding='utf-8'))['version']
    if not args.patch_only:
        if dest.exists() and any(dest.iterdir()):raise ValueError(f'Refusing to reset nonempty work directory: {dest}')
        dest.mkdir(parents=True,exist_ok=True)
        os.environ['GIT_LFS_SKIP_SMUDGE']='1'
        run('git','init',str(dest),cwd=ROOT)
        run('git','config','core.autocrlf','false',cwd=dest)
        run('git','config','core.longpaths','true',cwd=dest)
        run('git','remote','add','origin',lock['hop']['repository'],cwd=dest)
        run('git','-c','core.autocrlf=false','fetch','--depth=1','origin',lock['hop']['commit'],cwd=dest)
        run('git','-c','core.autocrlf=false','checkout','--detach','FETCH_HEAD',cwd=dest)
        run('git','-c','core.longpaths=true','-c','core.autocrlf=false','submodule','update','--init','--depth=1','--recursive',cwd=dest)
    if run('git','rev-parse','HEAD',cwd=dest)!=lock['hop']['commit']:raise ValueError('HOP commit mismatch')
    if run('git','rev-parse','HEAD',cwd=dest/'third_party/rhwp')!=lock['rhwp']['commit']:raise ValueError('rhwp submodule mismatch')
    if not args.patch_only:port_windows_contract_test(dest)
    if not args.fetch_only:patch(dest,version)
    print(f'Prepared {dest}; fetch_only={args.fetch_only}. Compilation and runtime verification are separate gates.')

if __name__=='__main__':
    try:main()
    except (ValueError,OSError,subprocess.CalledProcessError) as error:
        print(f'ERROR: {error}',file=sys.stderr);sys.exit(1)
