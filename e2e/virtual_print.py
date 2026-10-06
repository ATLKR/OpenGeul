"""Real Print UI -> owned Windows spooler -> independently rasterized PDF.
No direct-PDF or app test bridge. No physical/default printer is changed.
"""
from __future__ import annotations
import argparse,json,shutil,subprocess,time,traceback
from pathlib import Path
import xml.etree.ElementTree as ET
import psutil
from PIL import ImageGrab
from pywinauto import Desktop
from pywinauto.keyboard import send_keys
from driver import Session,digest,edit
from native_controls import filename_control
from print_raster import inspect_print_pdf
from print_queue import VirtualQueue,require_host

def wait(check,seconds=30):
    deadline=time.monotonic()+seconds
    while time.monotonic()<deadline:
        value=check()
        if value:return value
        time.sleep(.15)
    raise AssertionError('Timed out waiting for real printer UI/output')
def belongs_to(window,pid):
    try:return window.process_id()==pid or any(p.pid==pid for p in psutil.Process(window.process_id()).parents())
    except psutil.Error:return False
def visible_dialog(title,pid=None):
    found=[w for w in Desktop(backend='win32').windows(class_name='#32770',visible_only=True) if w.window_text()==title and (pid is None or belongs_to(w,pid))]
    if len(found)>1:raise AssertionError(f'Ambiguous native dialog: {title}')
    return found[0] if found else None
def control(dialog,cls,id):
    items=[w for w in dialog.descendants(class_name=cls) if w.control_id()==id and w.is_visible()]
    if len(items)!=1:raise AssertionError(f'Expected one {cls}/{id} in native print dialog')
    return items[0]
def snapshot(folder):
    ImageGrab.grab().save(folder/'native-screen.png');rows=[]
    for w in Desktop(backend='win32').windows(class_name='#32770',visible_only=True):
        rows.append({'title':w.window_text(),'pid':w.process_id(),'hwnd':w.handle,'children':[{'title':c.window_text(),'class':c.class_name(),'id':c.control_id()} for c in w.descendants() if c.is_visible()][:200]})
    (folder/'native-dialogs.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')
def system_dialog(session,queue):
    windows=[w for w in Desktop(backend='win32').windows(process=session.proc.pid,visible_only=True) if w.class_name()=='Tauri Window']
    if len(windows)!=1:raise AssertionError('Expected one owned app window')
    def viewports():return {c.handle for c in windows[0].descendants(class_name='Chrome_RenderWidgetHostHWND') if c.is_visible()}
    before=viewports();windows[0].set_focus();send_keys('^p');wait(lambda:viewports()-before)
    # Creating the native viewport precedes registering preview keyboard handlers.
    # One bounded human-input settle interval, not an automatic flaky-test retry.
    time.sleep(3);send_keys('^+p')
    dialog=wait(lambda:visible_dialog('Print',session.proc.pid))
    lists=[c for c in dialog.descendants(class_name='SysListView32') if c.is_visible()]
    if len(lists)!=1:raise AssertionError('Printer selection list was not found')
    item=lists[0].get_item(queue.name);item.select();wait(item.is_selected)
    if not item.is_selected():raise AssertionError('Owned printer is not selected')
    return dialog
def configure_media(dialog,pid,folder):
    control(dialog,'Button',1010).click_input()
    preferences=wait(lambda:visible_dialog('Printing Preferences',pid))
    control(preferences,'ComboBox',1232).select('Portrait')
    control(preferences,'Button',8000).click_input()
    advanced=wait(lambda:visible_dialog('Microsoft Print To PDF Advanced Options',pid))
    paper=control(advanced,'ComboBox',9060);paper.select('A4')
    if paper.selected_text()!='A4':raise AssertionError('Driver did not accept requested A4 media')
    (folder/'requested-media.json').write_text(json.dumps({'paper':paper.selected_text(),'orientation':'Portrait'}))
    control(advanced,'Button',1).click_input();control(preferences,'Button',1).click_input()
    wait(lambda:not visible_dialog('Printing Preferences',pid))
def print_document(exe,fixture,case,folder):
    folder.mkdir(parents=True,exist_ok=False);source=folder/fixture.name;shutil.copyfile(fixture,source)
    before=digest(source);output=folder/'printed.pdf';session=None
    try:
        with VirtualQueue() as queue:
            session=Session('native',folder/'session',source,executable=exe)
            if queue.jobs():raise AssertionError('Queue contains stale jobs')
            dialog=system_dialog(session,queue);configure_media(dialog,session.proc.pid,folder)
            if case.get('range'):
                control(dialog,'Button',1059).click_input();control(dialog,'Edit',1152).set_edit_text(case['range'])
            snapshot(folder)
            if case.get('cancel'):
                control(dialog,'Button',2).click_input();wait(lambda:not visible_dialog('Print',session.proc.pid))
                edit(session.page,' AFTER-PRINT-CANCEL ')
                if not session.page.title().startswith('• '):raise AssertionError('Editor is not usable after print cancellation')
                if queue.jobs() or output.exists():raise AssertionError('Cancelled print produced output')
                report={'cancelled':True,'jobs':[],'queue':queue.name}
            else:
                control(dialog,'Button',1).click_input();save=wait(lambda:visible_dialog('Save Print Output As'))
                filename_control(save.descendants()).set_edit_text(str(output));control(save,'Button',1).click_input()
                wait(lambda:output.is_file() and output.stat().st_size>100,90)
                wait(lambda:output.read_bytes().rstrip().endswith(b'%%EOF'),30)
                jobs=wait(queue.jobs,30)
                if len(jobs)!=1:raise AssertionError('Expected exactly one retained spooler job')
                job=jobs[0];bad=queue.api.JOB_STATUS_ERROR|queue.api.JOB_STATUS_OFFLINE|queue.api.JOB_STATUS_PAPEROUT
                if job['Status'] & bad:raise AssertionError(f'Spooler reported failure: {job["Status"]}')
                spool={'queue':queue.name,'jobs':[{k:job.get(k) for k in ('JobId','pPrinterName','pDocument','pDatatype','Status','TotalPages','PagesPrinted')}]}
                dm=job.get('pDevMode')
                if dm is not None:spool['jobMedia']={k:getattr(dm,k) for k in ('PaperSize','PaperLength','PaperWidth','FormName','Orientation')}
                (folder/'spooler.json').write_text(json.dumps(spool,ensure_ascii=False,indent=2),encoding='utf-8')
                report=inspect_print_pdf(output,{'pages':case['pages']},folder/'pdf-check',case['name']);report.update(spool)
            if digest(source)!=before:raise AssertionError('Printing modified the source document')
            report['sourceSha256']=before
            (folder/'result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
            return report
    except BaseException:snapshot(folder);raise
    finally:
        if session:
            subprocess.run(['taskkill','/PID',str(session.proc.pid),'/T','/F'],capture_output=True,timeout=15);session.close()
def main():
    require_host();parser=argparse.ArgumentParser()
    for name in ('exe','inputs','fixtures','out'):parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args();exe=args.exe.resolve();out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    cases=json.loads((args.fixtures/'print-cases.json').read_text(encoding='utf-8'))
    cases=[{**c,'path':args.fixtures/c['file']} for c in cases]
    basic={'pages':[{'size_pt':[595.28,841.86],'markers':['OpenGeul fixture','한글','123']}]}
    for suffix in ('hwp','hwpx'):cases.append({**basic,'name':'basic-'+suffix,'path':args.inputs/('basic.'+suffix)})
    multi=next(c for c in cases if c['name']=='multipage')
    cases.append({**multi,'name':'page-range','range':'2','pages':multi['pages'][1:]})
    cases.append({**basic,'name':'cancel','path':args.inputs/'basic.hwpx','cancel':True})
    if len(cases)!=8:raise AssertionError('Required print scenario count changed')
    results=[];suite=ET.Element('testsuite',name='virtual-print',tests=str(len(cases)),failures='0',skipped='0')
    for case in cases:
        item=ET.SubElement(suite,'testcase',name=case['name'])
        try:
            print('PRINT',case['name'],flush=True);print_document(exe,case['path'].resolve(),case,out/case['name'])
            results.append({'name':case['name'],'passed':True})
        except Exception:
            error=traceback.format_exc();print(error,flush=True);ET.SubElement(item,'failure').text=error
            results.append({'name':case['name'],'passed':False,'error':error})
    failures=sum(not r['passed'] for r in results);suite.set('failures',str(failures))
    ET.ElementTree(suite).write(out/'junit.xml',encoding='utf-8',xml_declaration=True)
    (out/'summary.json').write_text(json.dumps({'tests':8,'failures':failures,'skipped':0,'results':results},indent=2),encoding='utf-8')
    if failures:raise SystemExit(f'{failures} virtual-print scenarios failed')
    print('All 8 virtual-printer scenarios passed; physical devices are not certified.',flush=True)
if __name__=='__main__':main()
