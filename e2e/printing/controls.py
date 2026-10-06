"""Operate genuine, app-owned WebView2 and Windows print controls."""
import json
from pathlib import Path
import time
from pywinauto import Desktop
from PIL import ImageGrab
from driver import menu,until
from native_controls import filename_control

class PrintControls:
    def __init__(self,session,evidence:Path):
        self.session=session;self.evidence=evidence
        self.app=Desktop(backend='win32').window(process=session.proc.pid,class_name='Tauri Window')
        self.ui=Desktop(backend='uia').window(handle=self.app.handle)
    def open(self):
        menu(self.session.page,'file:print')
        # Renderer accessibility is opt-in for this test process, not a product modification.
        def links():return [c for c in self.ui.descendants(control_type='Hyperlink')
            if 'Print using system dialog' in c.window_text() and c.is_visible() and c.is_enabled()]
        found=until(links,30)
        if len(found)!=1:raise AssertionError('Ambiguous real print-preview action')
        found[0].click_input()
        def native():
            candidates=[c for c in self.ui.descendants(control_type='Window')
                if c.window_text()=='Print' and c.class_name()=='#32770' and c.is_visible()]
            if len(candidates)>1:raise RuntimeError('Ambiguous app-owned print dialog')
            return candidates
        handle=until(native,30)[0].handle
        self.dialog=Desktop(backend='win32').window(handle=handle)
        self.dialog.wait('visible',timeout=15)
        return self
    def cancel(self):
        self.dialog.child_window(control_id=2,class_name='Button',visible_only=True).click_input()
        self.dialog.wait_not('visible',timeout=20)
    def print(self,queue,target:Path,pages=None):
        if target.exists():raise ValueError('Refusing to overwrite output')
        queue.jobs() # Revalidate local driver/port/name immediately before sending.
        printers=self.dialog.child_window(class_name='SysListView32',visible_only=True)
        printers.select(queue.name)
        if not printers.get_item(queue.name).is_selected() or printers.get_selected_count()!=1:
            raise AssertionError('The isolated PDF queue was not selected')
        if pages is not None:
            if type(pages) is not int or not 1<=pages<=6:raise ValueError('Invalid test page range')
            self.dialog.child_window(control_id=1059,class_name='Button',visible_only=True).click_input()
            self.dialog.child_window(control_id=1152,class_name='Edit',visible_only=True).set_edit_text(str(pages))
        else:self.dialog.child_window(control_id=1056,class_name='Button',visible_only=True).click_input()
        before=queue.ids()
        self.dialog.child_window(control_id=1,class_name='Button',visible_only=True).click_input()
        save=Desktop(backend='win32').window(title='Save Print Output As',class_name='#32770')
        save.wait('visible',timeout=30)
        filename_control(save.descendants()).set_edit_text(str(target.resolve()))
        save.child_window(control_id=1,class_name='Button',visible_only=True).click_input()
        save.wait_not('visible',timeout=30)
        self.dialog.wait_not('visible',timeout=30)
        job=queue.wait_printed(before)
        (self.evidence/'spool-job.json').write_text(json.dumps(job,indent=2),encoding='utf-8')
        until(lambda:target.is_file() and target.stat().st_size>100,30)
        return job
    def capture(self):
        ImageGrab.grab().save(self.evidence/'desktop.png')
