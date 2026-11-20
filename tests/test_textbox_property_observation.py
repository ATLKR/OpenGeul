"""Numeric-only textbox observation regressions; no browser or original environment."""
import ast
import contextlib
import io
import json
from pathlib import Path
import re
import tempfile
import unittest

SOURCE=Path(__file__).resolve().parents[1]/'e2e/advanced_edit_cases.py'
NAME='textbox-property-observation.numeric.json'


def source_api():
    tree=ast.parse(SOURCE.read_text(encoding='utf-8'))
    nodes=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name.startswith('_textbox_')]
    namespace={'re':re,'json':json}
    exec(compile(ast.Module(body=nodes,type_ignores=[]),str(SOURCE),'exec'),namespace)
    return tree,namespace


def property_action():
    tree,namespace=source_api()
    owner=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='AdvancedEditCases')
    method=next(n for n in owner.body if isinstance(n,ast.FunctionDef) and
                n.name=='test_advanced_textbox_create_edit_history_reopen')
    def calls(statement,name):
        return [n for n in ast.walk(statement) if isinstance(n,ast.Call)
                and isinstance(n.func,ast.Attribute) and n.func.attr==name]
    first=next(i for i,n in enumerate(method.body) if calls(n,'fill'))
    last=next(i for i,n in enumerate(method.body) if any(
        c.args and isinstance(c.args[0],ast.Constant) and c.args[0].value=='properties'
        for c in calls(n,'advanced_check')))
    arguments=ast.arguments(posonlyargs=[],args=[ast.arg(arg=n) for n in ('self','panel','d','verify')],
                            kwonlyargs=[],kw_defaults=[],defaults=[])
    function=ast.FunctionDef(name='action',args=arguments,body=method.body[first:last+1],
                             decorator_list=[])
    module=ast.fix_missing_locations(ast.Module(body=[function],type_ignores=[]))
    exec(compile(module,str(SOURCE),'exec'),namespace)
    return namespace['action']


class SecretError(RuntimeError):
    def __str__(self):raise AssertionError('Exception text must not be accessed')
    def __repr__(self):raise AssertionError('Exception representation must not be accessed')


class Panel:
    def __init__(self,events,*,misdeliver=False,failures=None,values=None):
        self.events=events;self.misdeliver=misdeliver;self.failures=failures or {}
        self.values=list(values) if values is not None else ['39.95','20.11']
    def locator(self,selector):
        if selector!='input[type=number]':raise AssertionError('Unexpected locator')
        return self
    def nth(self,index):
        if type(index)is not int or index not in (0,1):raise AssertionError('Unexpected input index')
        return Number(self,index)


class Number:
    def __init__(self,panel,index):self.panel=panel;self.index=index
    def fill(self,value):
        if type(value)is not str or value!=('45','25')[self.index]:
            raise AssertionError('Original authored input changed')
        self.panel.events.append(10+self.index)
        target=0 if self.panel.misdeliver and self.index==1 else self.index
        self.panel.values[target]=value
    def input_value(self,*,timeout):
        if type(timeout)is not int or not 0<timeout<=1000:raise AssertionError('Unbounded observation')
        self.panel.events.append(20+self.index)
        if self.index in self.panel.failures:raise self.panel.failures[self.index]
        return self.panel.values[self.index]


class Dialog:
    def __init__(self,events,error=None):self.events=events;self.error=error
    def locator(self,selector):
        if selector!='.cs-right-col .dialog-btn-primary':raise AssertionError('Apply target changed')
        return self
    def click(self):
        self.events.append(30)
        if self.error is not None:raise self.error


class Owner:
    def __init__(self,folder,events):self.folder=folder;self.events=events
    def advanced_check(self,label,oracle):
        if label!='properties':raise AssertionError('Original checkpoint changed')
        self.events.append(40);oracle(None)


class TextboxPropertyObservationTests(unittest.TestCase):
    def api(self,name):
        value=source_api()[1].get(name)
        self.assertTrue(callable(value),'Numeric observation boundary is missing')
        return value

    def read(self,folder):
        raw=(folder/NAME).read_bytes()
        self.assertTrue(len(raw)<=1024,'Numeric receipt exceeded bound')
        row=json.loads(raw)
        self.assertTrue(set(row)=={'schemaVersion','diagnosticOnly','qualification','normalAcceptance',
            'fullEngineQualified','acceptanceEligible','guiVerified','valuesMm100','errorCodes'},
            'Numeric receipt shape changed')
        self.assertTrue(row['schemaVersion']==1 and row['diagnosticOnly']is True)
        self.assertTrue(all(row[k]is False for k in ('qualification','normalAcceptance',
            'fullEngineQualified','acceptanceEligible','guiVerified')))
        self.assertTrue(type(row['valuesMm100'])is list and len(row['valuesMm100'])==2)
        self.assertTrue(all(x is None or type(x)is int and 0<=x<=999999 for x in row['valuesMm100']))
        self.assertTrue(type(row['errorCodes'])is list and len(row['errorCodes'])==2)
        self.assertTrue(all(type(x)is int and 0<=x<=7 for x in row['errorCodes']))
        return row

    def test_dimensions_are_exact_integer_hundredths_without_rounding(self):
        convert=self.api('_textbox_mm100')
        for ordinal,(value,want) in enumerate((('45',4500),('45.00',4500),('25',2500),
                ('20.11',2011),('0',0),('0.01',1),('9999.99',999999))):
            with self.subTest(caseCode=ordinal):
                self.assertTrue(convert(value)==want,'Wrong numeric conversion')

    def test_malformed_values_never_become_defaults_or_coerced_dimensions(self):
        convert=self.api('_textbox_mm100')
        values=('', ' ', ' 45','45\n','+45','-1','4.5e1','45.001','NaN','Infinity',
                '４５','1'*10000,45,True,None,SecretError())
        for ordinal,value in enumerate(values):
            with self.subTest(caseCode=ordinal):
                self.assertTrue(convert(value)is None,'Invalid input became an observed dimension')

    def test_actual_property_action_reads_once_after_fills_before_apply(self):
        with tempfile.TemporaryDirectory()as directory:
            folder=Path(directory);events=[];panel=Panel(events)
            def verify(_result,count,text,dimensions):
                self.assertTrue(count==1 and dimensions==(45,25),'Original property oracle changed')
            property_action()(Owner(folder,events),panel,Dialog(events),verify)
            self.assertTrue(events==[10,11,20,21,30,40],'Property input/observation order changed')
            row=self.read(folder)
            self.assertTrue(row['valuesMm100']==[4500,2500] and row['errorCodes']==[0,0])

    def test_misdelivered_value_is_observed_without_replacing_the_original_apply_error(self):
        with tempfile.TemporaryDirectory()as directory:
            folder=Path(directory);events=[];primary=SecretError()
            with self.assertRaises(SecretError)as caught:
                property_action()(Owner(folder,events),Panel(events,misdeliver=True),Dialog(events,primary),lambda *_:None)
            self.assertTrue(caught.exception is primary,'Original Apply exception identity changed')
            self.assertTrue(events==[10,11,20,21,30])
            row=self.read(folder)
            self.assertTrue(row['valuesMm100']==[2500,2011] and row['errorCodes']==[0,0])

    def test_invalid_value_records_null_and_does_not_expose_source_text(self):
        observe=self.api('_textbox_preapply')
        with tempfile.TemporaryDirectory()as directory:
            folder=Path(directory);events=[]
            observe(Panel(events,values=['SYNTHETIC_SECRET_VALUE','25']),folder)
            row=self.read(folder)
            self.assertTrue(row['valuesMm100']==[None,2500] and row['errorCodes']==[1,0])
            self.assertTrue(events==[20,21])

    def test_read_errors_are_fixed_codes_and_do_not_retry_or_replace_apply(self):
        failures=[(TimeoutError(),2),(type('TargetClosedError',(Exception,),{})(),3),
                  (type('Error',(Exception,),{})(),4),(OSError(),5),(PermissionError(),6),(SecretError(),7)]
        for ordinal,(error,code)in enumerate(failures):
            with self.subTest(caseCode=ordinal),tempfile.TemporaryDirectory()as directory:
                folder=Path(directory);events=[];primary=SecretError()
                with self.assertRaises(SecretError)as caught:
                    property_action()(Owner(folder,events),Panel(events,failures={0:error}),
                                      Dialog(events,primary),lambda *_:None)
                self.assertTrue(caught.exception is primary)
                row=self.read(folder)
                self.assertTrue(row['valuesMm100']==[None,2500] and row['errorCodes']==[code,0])
                self.assertTrue(events==[10,11,20,21,30])

    def test_diagnostic_write_failure_does_not_replace_original_apply_failure(self):
        with tempfile.TemporaryDirectory()as directory:
            folder=Path(directory);(folder/NAME).mkdir();events=[];primary=SecretError()
            with self.assertRaises(SecretError)as caught:
                property_action()(Owner(folder,events),Panel(events),Dialog(events,primary),lambda *_:None)
            self.assertTrue(caught.exception is primary)
            self.assertTrue(events==[10,11,20,21,30])

    def test_user_cancellation_propagates_without_later_input_reads(self):
        observe=self.api('_textbox_preapply')
        for ordinal,cancellation in enumerate((KeyboardInterrupt(),SystemExit(17))):
            for field in (0,1):
                with self.subTest(caseCode=ordinal,fieldCode=field),tempfile.TemporaryDirectory()as directory:
                    folder=Path(directory);events=[]
                    with self.assertRaises(type(cancellation))as caught:
                        observe(Panel(events,failures={field:cancellation}),folder)
                    self.assertTrue(caught.exception is cancellation)
                    self.assertTrue(events==([20]if field==0 else[20,21]) and not(folder/NAME).exists())
            class CancelWrite:
                def __truediv__(self,name):return self
                def write_text(self,*args,**kwargs):raise cancellation
            events=[]
            with self.assertRaises(type(cancellation))as caught:
                observe(Panel(events),CancelWrite())
            self.assertTrue(caught.exception is cancellation and events==[20,21])

    def test_observation_emits_no_stdout_stderr_or_exception_representations(self):
        observe=self.api('_textbox_preapply')
        with tempfile.TemporaryDirectory()as directory:
            output=io.StringIO()
            with contextlib.redirect_stdout(output),contextlib.redirect_stderr(output):
                observe(Panel([],failures={0:SecretError()},values=['45','25']),Path(directory))
            self.assertTrue(output.getvalue()=='','Diagnostic produced raw output')
            self.read(Path(directory))


if __name__=='__main__':unittest.main()
