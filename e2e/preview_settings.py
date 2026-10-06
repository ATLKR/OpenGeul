"""Configure real WebView2 preview through its native accessibility controls.

The browser preview and the system driver have independent paper/margin state.
Both must match the synthetic document. No internal browser state or test bridge
is changed, and every possibly dispatched action is executed at most once.
"""
from __future__ import annotations
import json,time
from pathlib import Path
from print_focus import _node
from preview_policy import dropdown_index,option_index,validate_settings


def wait(read,seconds=30):
    end=time.monotonic()+seconds
    while time.monotonic()<end:
        value=read()
        if value is not None and value is not False:return value
        time.sleep(.15)
    raise AssertionError('Print preview setting did not reach the requested state')


def rows(preview):
    controls=preview.descendants();nodes=[]
    for c in controls:
        node=_node(c)
        if node['type']=='ComboBox':
            p=c.parent()
            for _ in range(4):
                if p.element_info.control_type=='Group' and p.window_text() in ('Paper size','Margins'):
                    node['group']=p.window_text();break
                p=p.parent()
        nodes.append(node)
    return controls,nodes


def dropdown(preview,label,pids):
    controls,nodes=rows(preview);i=dropdown_index(nodes,label,pids)
    return controls[i] if i is not None else None


def selected(control,label):
    name=control.window_text()
    if control.element_info.control_type=='Button':return name.removeprefix(label+' ')
    return control.iface_value.CurrentValue


def configure_preview(preview,pids,folder:Path|None=None):
    if preview.window_text()!='Print' or preview.class_name()!='RootView' or preview.process_id() not in pids:
        raise AssertionError('Cannot configure a foreign print preview')
    more=[c for c in preview.descendants(control_type='Button') if c.window_text()=='More settings' and c.is_enabled()]
    if len(more)>1:raise AssertionError('Ambiguous More settings action')
    if more:
        from pywinauto.uia_defines import NoPatternInterfaceError
        try:pattern=more[0].iface_expand_collapse
        except NoPatternInterfaceError:pattern=None
        if pattern is not None:pattern.Expand()
        else:more[0].iface_invoke.Invoke()
    state={}
    try:
        for label,value,key in (('Paper size','A4','paper'),('Margins','None','margins')):
            target=wait(lambda:dropdown(preview,label,pids))
            before=selected(target,label)
            state[key+'Before']=before
            if before!=value:
                target.iface_expand_collapse.Expand()
                def option():
                    controls,nodes=rows(preview);i=option_index(nodes,value,pids)
                    return controls[i] if i is not None else None
                choice=wait(option)
                choice.iface_selection_item.Select()
                current=wait(lambda:dropdown(preview,label,pids))
                if current.iface_expand_collapse.CurrentExpandCollapseState==1:
                    current.iface_expand_collapse.Collapse()
            wait(lambda:selected(dropdown(preview,label,pids),label)==value)
            state[key]=value
        actual=[c for c in preview.descendants(control_type='RadioButton') if c.window_text()=='Actual size' and c.is_enabled() and c.process_id() in pids]
        if len(actual)!=1:raise AssertionError('Actual size choice is not unique')
        if not actual[0].iface_selection_item.CurrentIsSelected:actual[0].iface_selection_item.Select()
        state['actualSize']=bool(actual[0].iface_selection_item.CurrentIsSelected)
        validate_settings(state)
        return state
    finally:
        if folder:
            _,nodes=rows(preview)
            (folder/'preview-settings.json').write_text(json.dumps({'requested':state,'controls':nodes},ensure_ascii=False,indent=2),encoding='utf-8')
