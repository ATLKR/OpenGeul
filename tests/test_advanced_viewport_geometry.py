"""Measured page geometry, independent of Playwright and document contents."""
import ast
import copy
import math
import json
from pathlib import Path
import shutil
import subprocess
import unittest
from contextlib import contextmanager

SOURCE=Path(__file__).resolve().parents[1]/'e2e/advanced_edit_cases.py'


class AdvancedViewportGeometryTests(unittest.TestCase):
    def api(self,name):
        tree=ast.parse(SOURCE.read_text(encoding='utf-8'))
        nodes=[node for node in tree.body if isinstance(node,ast.FunctionDef) and node.name.startswith('_advanced_')]
        self.assertIn(name,{node.name for node in nodes},'Measured viewport boundary is required')
        namespace={'math':math}
        exec(compile(ast.Module(body=nodes,type_ignores=[]),str(SOURCE),'exec'),namespace)
        return namespace[name]

    def controller(self):
        tree=ast.parse(SOURCE.read_text(encoding='utf-8'))
        nodes=[node for node in tree.body if isinstance(node,ast.FunctionDef) and node.name.startswith('_advanced_')
               or isinstance(node,ast.ClassDef) and node.name=='AdvancedEditCases']
        namespace={'math':math,'contextmanager':contextmanager}
        exec(compile(ast.Module(body=nodes,type_ignores=[]),str(SOURCE),'exec'),namespace)
        value=namespace['AdvancedEditCases']()
        self.assertTrue(callable(getattr(value,'advanced_canvas_plan',None)), 'Input must retain its measured canvas plan')
        return value

    def frame(self):
        return {'canvas':{'x':200.,'y':160.,'width':800.,'height':1200.},
            'clip':{'x':100.,'y':140.,'width':1100.,'height':740.},
            'viewport':[1280.,900.,1.],'window':[0.,0.],'scroll':[0.,0.],
            'pixels':[800,1200],'identity':[True]*5}

    def test_two_drag_endpoints_are_derived_from_one_visible_page_frame(self):
        frame=self.frame();frame['canvas'].update(width=840.,height=1188.);frame['pixels']=[840,1188]
        points=self.api('_advanced_points')(frame,[(75,70),(115,90)])
        self.assertEqual(points,[{'x':500.,'y':440.},{'x':660.,'y':520.}])

    def test_ci_firefox_centered_page_cannot_authorize_the_covered_nested_point(self):
        function=self.api('_advanced_points')
        frame=self.frame();frame['canvas'].update(x=253.14999389648438,y=-50.75,width=793.6999816894531,height=1122.5)
        frame['clip'].update(x=0.,y=153.,width=1280.,height=725.)
        with self.assertRaises(AssertionError):function(frame,[(42,43)])

    def test_point_outside_the_declared_page_cannot_become_another_page_input(self):
        function=self.api('_advanced_points')
        for points in ([(211,43)],[(42,298)],[(float('nan'),43)],[]):
            with self.subTest(case=len(points)):
                with self.assertRaises(AssertionError):function(self.frame(),points)

    def test_disconnected_replaced_or_foreign_page_identity_is_rejected(self):
        function=self.api('_advanced_points')
        for index in range(5):
            frame=self.frame();frame['identity'][index]=False
            with self.subTest(identity=index):
                with self.assertRaises(AssertionError):function(frame,[(42,43)])

    def test_identity_must_be_observed_booleans_not_truthy_metadata(self):
        function=self.api('_advanced_points')
        frame=self.frame();frame['identity'][0]=1
        with self.assertRaises(AssertionError):function(frame,[(42,43)])

    def test_only_measured_scroller_translation_can_change_the_canvas_position(self):
        before=self.frame();after=copy.deepcopy(before)
        after['canvas']['y']=60.;after['scroll'][1]=100.
        self.assertEqual(self.api('_advanced_same_frame')(before,after,scrolled=True),after)
        with self.assertRaises(AssertionError):self.api('_advanced_same_frame')(before,after)

    def test_unexplained_canvas_motion_is_not_a_scroll_observation(self):
        function=self.api('_advanced_same_frame')
        before=self.frame();after=copy.deepcopy(before);after['canvas']['y']=60.
        with self.assertRaises(AssertionError):function(before,after,scrolled=True)

    def test_viewport_backing_and_scroller_changes_invalidate_a_retained_frame(self):
        function=self.api('_advanced_same_frame');before=self.frame()
        for field,change in [('viewport',[1280.,901.,1.]),('pixels',[801,1200]),('window',[0.,1.])]:
            after=copy.deepcopy(before);after[field]=change
            with self.subTest(field=field):
                with self.assertRaises(AssertionError):function(before,after,scrolled=True)
        after=copy.deepcopy(before);after['clip']['height']=739.
        with self.assertRaises(AssertionError):function(before,after,scrolled=True)

    def test_visible_viewport_crop_uses_its_own_pixel_coordinate_frame(self):
        clip,box,points=self.api('_advanced_capture')(self.frame(),(.125,1/12,.175,13/120))
        self.assertEqual(clip,{'x':200,'y':160,'width':800,'height':720})
        for got,want in zip(box,(.125,.1388888888888889,.175,.18055555555555555)):
            self.assertAlmostEqual(got,want,places=12)
        self.assertEqual(points,[{'x':301.,'y':261.},{'x':339.,'y':261.},
            {'x':339.,'y':289.},{'x':301.,'y':289.},{'x':320.,'y':275.}])

    def test_partial_or_offscreen_equation_cannot_be_measured_as_visible_ink(self):
        function=self.api('_advanced_capture')
        for box in ((.125,.7,.175,.75),(-.001,.1,.1,.2),(.9,.1,1.001,.2),(.1,.1,.1,.2)):
            with self.subTest(case=box[0]):
                with self.assertRaises(AssertionError):function(self.frame(),box)

    def test_empty_visible_canvas_or_tiny_equation_cannot_produce_a_capture(self):
        function=self.api('_advanced_capture');frame=self.frame();frame['clip']['x']=1200.
        with self.assertRaises(AssertionError):function(frame,(.125,1/12,.175,13/120))
        with self.assertRaises(AssertionError):function(self.frame(),(.125,1/12,.126,13/120))

    def test_unknown_or_nonfinite_frame_cannot_hide_a_geometry_change(self):
        function=self.api('_advanced_points')
        frame=self.frame();frame['unreviewed']=True
        with self.assertRaises(AssertionError):function(frame,[(42,43)])
        frame=self.frame();frame['canvas']['width']=float('inf')
        with self.assertRaises(AssertionError):function(frame,[(42,43)])

    def test_selected_border_and_canvas_are_consumed_from_one_stable_observation(self):
        function=self.api('_advanced_selection');frame=self.frame()
        observed={'before':frame,'after':copy.deepcopy(frame),'hits':[],
            'selection':[{'x':300.,'y':260.,'width':40.,'height':30.}]}
        actual,box=function(observed)
        self.assertEqual(actual,frame)
        self.assertEqual(box,(.125,1/12,.175,13/120))

    def test_selection_cannot_join_a_box_to_a_moved_canvas_frame(self):
        function=self.api('_advanced_selection');frame=self.frame();after=copy.deepcopy(frame)
        after['canvas']['y']=60.;after['scroll'][1]=100.
        observed={'before':frame,'after':after,'hits':[],
            'selection':[{'x':300.,'y':260.,'width':40.,'height':30.}]}
        with self.assertRaises(AssertionError):function(observed)

    def test_actual_click_rejects_canvas_replacement_after_input(self):
        controller=self.controller();page=PublicPage(self.frame());controller.page=page
        controller.area=lambda:page.input
        with self.assertRaises(AssertionError):controller.advanced_click_mm(42,43)
        self.assertEqual(page.clicks,1)
        self.assertTrue(page.canvas.disposed and page.scroller.disposed)

    def test_drag_plan_retains_handles_and_rejects_backing_change_at_consumption(self):
        controller=self.controller();page=PublicPage(self.frame());controller.page=page
        with self.assertRaises(AssertionError):
            with controller.advanced_canvas_plan([(75,70),(115,90)]) as points:
                self.assertEqual(len(points),2)
                self.assertFalse(page.canvas.disposed or page.scroller.disposed)
                page.frame['pixels'][0]+=1
        self.assertTrue(page.canvas.disposed and page.scroller.disposed)

    def test_actual_canvas_javascript_scrolls_only_its_finite_owned_scroller(self):
        tree=ast.parse(SOURCE.read_text(encoding='utf-8'))
        owner=next(node for node in tree.body if isinstance(node,ast.ClassDef) and node.name=='AdvancedEditCases')
        method=next(node for node in owner.body if isinstance(node,ast.FunctionDef) and node.name=='advanced_canvas_snapshot')
        call=next(node for node in ast.walk(method) if isinstance(node,ast.Call)
                  and isinstance(node.func,ast.Attribute) and node.func.attr=='evaluate')
        callback=ast.literal_eval(call.args[0])
        node=shutil.which('node');self.assertIsNotNone(node,'Actual embedded JavaScript requires the existing Node runtime')
        script='const callback=('+callback+');'+'''
          function observe(nonfinite) {
            globalThis.window=globalThis;globalThis.innerWidth=1280;globalThis.innerHeight=900;
            globalThis.devicePixelRatio=1;globalThis.scrollX=0;globalThis.scrollY=0;
            let scrollCalls=0;
            const scroller={isConnected:true,clientLeft:0,clientTop:0,clientWidth:1260,clientHeight:738,
              scrollLeft:0,scrollTop:0,contains:n=>n===node,
              getBoundingClientRect:()=>({x:20,y:140-scrollY,width:1260,height:738}),
              scrollTo:p=>{scrollCalls++;scroller.scrollLeft=p.left;scroller.scrollTop=p.top;}};
            const node={isConnected:true,width:794,height:1123,
              getBoundingClientRect:()=>({x:253.15625,y:nonfinite?Infinity:150-scrollY-scroller.scrollTop,width:793.6875,height:1122.5}),
              // Browser scrollIntoView can also move an outer window by 2px.
              scrollIntoView:()=>{scrollCalls++;scroller.scrollTop=10;globalThis.scrollY=2;}};
            globalThis.document={defaultView:globalThis,querySelector:s=>s==='#scroll-container'?scroller:node};
            node.ownerDocument=document;
            try {const observed=callback(node,{scroller,scroll:true,points:[],selected:false});
              return nonfinite?{rejected:false,scrollCalls,window:[scrollX,scrollY]}:observed;
            } catch(error) {return {rejected:true,scrollCalls,window:[scrollX,scrollY]};}
          }
          process.stdout.write(JSON.stringify([observe(false),observe(true)]));
        '''
        result=subprocess.run([node,'-e',script],capture_output=True,text=True,timeout=10,env={})
        self.assertEqual(result.returncode,0,'Actual public canvas JavaScript execution failed')
        valid,invalid=json.loads(result.stdout)
        self.api('_advanced_same_frame')(valid['before'],valid['after'],scrolled=True)
        self.assertEqual(valid['after']['window'],[0,0])
        self.assertEqual(valid['after']['scroll'],[0,10])
        self.assertEqual(invalid,{'rejected':True,'scrollCalls':0,'window':[0,0]})


class PublicHandle:
    def __init__(self,page):self.page=page;self.disposed=False
    def dispose(self):self.disposed=True
    def evaluate(self,expression,args):
        before=copy.deepcopy(self.page.frame)
        return {'before':before,'after':copy.deepcopy(before),
            'hits':[True]*len(args['points']),'selection':[]}


class PublicLocator:
    def __init__(self,handle):self.handle=handle
    @property
    def first(self):return self
    def element_handle(self):return self.handle


class PublicPage:
    def __init__(self,frame):
        self.frame=frame;self.canvas=PublicHandle(self);self.scroller=PublicHandle(self)
        self.mouse=self;self.input=self;self.clicks=0
    def locator(self,selector):
        if selector=='canvas.document-page-canvas':return PublicLocator(self.canvas)
        if selector=='#scroll-container':return PublicLocator(self.scroller)
        raise AssertionError('Unexpected public selector')
    def click(self,x,y):self.clicks+=1;self.frame['identity'][1]=False
    def focus(self):pass


if __name__=='__main__':unittest.main()
