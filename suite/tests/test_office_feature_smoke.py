"""Portable adversarial checks; these do not execute the Windows Office engine."""
from contextlib import redirect_stdout
import copy
import importlib.util
import io
import json
import sqlite3
import sys
from types import SimpleNamespace
import zipfile
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1] / 'e2e/office_feature_smoke.py'
SPEC = importlib.util.spec_from_file_location('office_feature_smoke', SOURCE) if SOURCE.exists() else None
smoke = importlib.util.module_from_spec(SPEC) if SPEC else None
if SPEC: SPEC.loader.exec_module(smoke)

FORMAT_IDS = ('format-writer-odt', 'format-writer-docx', 'format-writer-doc', 'format-writer-rtf', 'format-writer-txt',
              'format-calc-ods', 'format-calc-xlsx', 'format-calc-xls', 'format-calc-csv',
              'format-impress-odp', 'format-impress-pptx', 'format-impress-ppt',
              'format-draw-odg', 'format-math-odf', 'format-base-odb')
RICH_IDS = ('rich-writer', 'rich-calc', 'rich-impress', 'rich-draw', 'rich-math', 'rich-base')


def successful_cleanup(suite):
    member = dict(pid=42, creationTime=123, handleValue=99, image=str(suite / 'Office/program/soffice.bin'), alive=True, exitCode=259)
    return dict(schemaVersion=1, kind='owned-engine-job-cleanup', jobHandleValue=11,
                expectedEngineImage=member['image'], gracefulQualified=True, forcedTermination=False,
                jobEmptyVerified=True, initialMembers=[member], finalMembers=[dict(member, alive=False, exitCode=0)],
                finalJobPids=[], launcherExitCode=0, errors=[])


class SemanticContractTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(smoke, 'The executable Office feature harness is missing')
        self.cases = {case['id']: case for case in smoke.case_specs()}

    def test_catalog_has_fixed_fifteen_formats_and_six_rich_cases(self):
        self.assertEqual(tuple(self.cases), FORMAT_IDS + RICH_IDS)
        self.assertEqual(21, len(self.cases))
        for case in self.cases.values():
            self.assertFalse(case['guiVerified'])
            smoke.validate_observation(case, smoke.expected(case))

    def test_catalog_rejects_missing_duplicate_extra_and_filter_drift(self):
        catalog = json.loads(smoke.CATALOG.read_text(encoding='utf-8'))
        for change in ('missing', 'duplicate', 'extra', 'filter'):
            with self.subTest(change=change):
                bad = copy.deepcopy(catalog)
                if change == 'missing': bad['cases'].pop()
                elif change == 'duplicate': bad['cases'][1] = copy.deepcopy(bad['cases'][0])
                elif change == 'extra': bad['cases'].append(dict(bad['cases'][0], id='invented'))
                else: bad['cases'][0]['filter'] = 'invented filter'
                with self.assertRaises((ValueError, AssertionError)):
                    smoke.validate_catalog(bad)

    def reject(self, id, mutate):
        case = self.cases[id]
        observed = copy.deepcopy(smoke.expected(case))
        mutate(observed)
        with self.assertRaises((ValueError, AssertionError)):
            smoke.validate_observation(case, observed)

    def test_rich_representative_format_and_top_level_claims_cannot_drift(self):
        catalog = json.loads(smoke.CATALOG.read_text(encoding='utf-8'))
        for field, value in [('expectedCaseCount', 20), ('guiVerified', True), ('officeReplacementCertified', True)]:
            bad = copy.deepcopy(catalog)
            bad[field] = value
            with self.assertRaises(ValueError): smoke.validate_catalog(bad)
        bad = copy.deepcopy(catalog)
        bad['cases'][15].update(extension='odt', filter='writer8')
        with self.assertRaises(ValueError): smoke.validate_catalog(bad)

    def test_flat_options_explicitly_select_utf8_and_disable_formula_import_export(self):
        self.assertEqual(smoke.TEXT_OPTIONS, 'UTF8,LF,,,false,false')
        self.assertEqual(smoke.CSV_OPTIONS.split(','),
                         ['44','34','76','1','','0','false','true','false','false','false','0','false','false'])

    def test_writer_missing_table_cannot_pass(self):
        self.reject('rich-writer', lambda o: o.update(tables=[]))

    def test_writer_wrong_cell_and_unbolded_paragraph_cannot_pass(self):
        self.reject('rich-writer', lambda o: o['tables'][0]['cells'].update(A2='wrong'))
        self.reject('rich-writer', lambda o: o['paragraphs'][0].update(bold=False))

    def test_writer_plain_requires_uniform_normal_weight_in_every_visible_run(self):
        class Enumeration:
            def __init__(self,values): self.values=iter(values); self.next=next(self.values,None)
            def hasMoreElements(self): return self.next is not None
            def nextElement(self):
                result=self.next; self.next=next(self.values,None); return result
        def paragraph(weights):
            portions=[SimpleNamespace(getString=lambda:'x',getPropertyValue=lambda name,w=w:w) for w in weights]
            return SimpleNamespace(getString=lambda:'Plain paragraph',createEnumeration=lambda:Enumeration(portions))
        self.assertTrue(callable(getattr(smoke,'writer_paragraph',None)), 'Exact visible text-run weight observer is missing')
        self.assertEqual([100,100,100],smoke.writer_paragraph(paragraph([100,100]))['weights'])
        for weights in ([175], [100,150], [None]):
            observed=smoke.writer_paragraph(paragraph(weights))
            case=self.cases['rich-writer']
            wrong=smoke.expected(case)
            wrong['paragraphs'][1]=observed
            with self.assertRaises(AssertionError): smoke.validate_observation(case,wrong)

    def test_base_odf_mimetype_matches_pinned_libreoffice_constant(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'owned.odb'
            case=self.cases['rich-base']
            for suffix in ('base','database'):
                with zipfile.ZipFile(path,'w') as package:
                    package.writestr('mimetype','application/vnd.oasis.opendocument.'+suffix)
                    package.writestr('content.xml','<document/>')
                if suffix=='base': smoke.validate_container(case,path)
                else:
                    with self.assertRaises(AssertionError): smoke.validate_container(case,path)

    def test_writer_unintended_plain_paragraph_format_cannot_pass(self):
        self.reject('rich-writer', lambda o: o['paragraphs'][1].update(bold=True))

    def test_calc_wrong_sum_formula_or_named_range_cannot_pass(self):
        self.reject('rich-calc', lambda o: o.update(value=42))
        self.reject('rich-calc', lambda o: o.update(formula='55'))
        self.reject('rich-calc', lambda o: o.update(namedRange=[0, 1, 1, 1, 1]))
        self.reject('rich-calc', lambda o: o.update(sheetNames=['Inputs']))

    def test_impress_missing_slide_wrong_order_and_geometry_cannot_pass(self):
        self.reject('rich-impress', lambda o: o['pages'].pop())
        self.reject('rich-impress', lambda o: o['pages'].reverse())
        self.reject('rich-impress', lambda o: o['pages'][1][0].update(size=[1, 1]))

    def test_legacy_ppt_fixture_is_exactly_aligned_to_576dpi_storage_grid(self):
        shape=smoke.expected(self.cases['format-impress-ppt'])['pages'][0][0]
        for value in shape['position']+shape['size']:
            self.assertEqual(0,(value*576)%2540,'PPT geometry would be quantized')

    def test_draw_page_color_or_geometry_loss_cannot_pass(self):
        self.reject('rich-draw', lambda o: o['pages'].pop())
        self.reject('rich-draw', lambda o: o['pages'][1][0].update(color=0))
        self.reject('rich-draw', lambda o: o['pages'][0][0].update(position=[0, 0]))

    def test_math_unchanged_formula_cannot_pass(self):
        self.reject('rich-math', lambda o: o.update(formula='sumfrom{i=1}to{4}i=10'))

    def test_base_unchanged_crud_deleted_or_rolledback_rows_cannot_pass(self):
        self.reject('rich-base', lambda o: o.update(rows=[{'id': 1, 'text': smoke.marker('base'), 'amount': 42}]))
        self.reject('rich-base', lambda o: o['rows'].append({'id': 2, 'text': 'deleted', 'amount': 9}))
        self.reject('rich-base', lambda o: o['rows'][0].update(amount=999))
        self.reject('rich-base', lambda o: o.update(databaseUrl='jdbc:'))

    def test_basic_formulas_and_exact_text_are_not_substring_success(self):
        self.reject('format-calc-xlsx', lambda o: o.update(value=43))
        self.reject('format-calc-xlsx', lambda o: o.update(formula='42'))
        self.reject('format-writer-docx', lambda o: o.update(text=o['text'] + o['text']))
        self.reject('format-impress-pptx', lambda o: o['pages'][0].append(copy.deepcopy(o['pages'][0][0])))

    def test_csv_loss_contract_requires_values_not_formula_or_format(self):
        case = self.cases['format-calc-csv']
        expected = smoke.expected(case)
        self.assertNotIn('formula', expected)
        self.assertEqual(expected['values'], [17, 25, 42])
        self.assertEqual(case['lossBudget'], ['formula-expression', 'formatting', 'extra-sheets'])
        self.reject(case['id'], lambda o: o.update(values=[17, 25, 0]))

    def test_text_loss_contract_requires_only_exact_normalized_unicode_text(self):
        case = self.cases['format-writer-txt']
        self.assertEqual(set(smoke.expected(case)), {'text'})
        self.assertIn('formatting', case['lossBudget'])
        self.reject(case['id'], lambda o: o.update(text='mojibake'))

    def test_explicit_text_csv_byte_oracles_reject_wrong_encoding_delimiter_or_formulas(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            txt = root/'fixture.txt'
            txt.write_bytes(('Engine-OpenGeul-writer 한글'+'\r\n').encode('utf-8'))
            smoke.validate_flat_bytes(self.cases['format-writer-txt'], txt)
            txt.write_bytes(b'wrong')
            with self.assertRaises(AssertionError): smoke.validate_flat_bytes(self.cases['format-writer-txt'], txt)
            csv = root/'fixture.csv'
            csv.write_text('Engine-OpenGeul-calc 한글'+',17,25,42\n', encoding='utf-8')
            smoke.validate_flat_bytes(self.cases['format-calc-csv'], csv)
            for payload in ('Engine-OpenGeul-calc 한글'+';17;25;42\n', 'Engine-OpenGeul-calc 한글'+',17,25,=SUM(B1:C1)\n'):
                csv.write_text(payload, encoding='utf-8')
                with self.assertRaises(AssertionError): smoke.validate_flat_bytes(self.cases['format-calc-csv'], csv)


class ExecutionBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(smoke, 'The executable Office feature harness is missing')
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.suite = self.root/'suite'
        self.suite.mkdir()
        self.output = self.root/'evidence'
        self.output.mkdir()
        (self.output/'fixtures').mkdir()
        self.cases = smoke.case_specs()

    def test_report_rejects_missing_duplicate_failure_or_gui_claim(self):
        good = [dict(case=case['id'], module=case['module'], status='passed', guiVerified=False,
                     sha256='a'*64, bytes=12, independentReopenVerified=True) for case in self.cases]
        self.assertTrue(smoke.summarize(good, self.suite)['passed'])
        variants = [good[:-1], good + [good[0]], [dict(row, status='failed') if i == 3 else row for i,row in enumerate(good)],
                    [dict(row, guiVerified=True) if i == 3 else row for i,row in enumerate(good)]]
        for rows in variants:
            with self.subTest(rows=len(rows)):
                self.assertFalse(smoke.summarize(rows, self.suite)['passed'])

    def test_aggregate_rejects_reordered_cases_nonhex_digest_and_cleanup_errors(self):
        good = [dict(case=case['id'], module=case['module'], status='passed', guiVerified=False,
                     sha256='a'*64, bytes=12, independentReopenVerified=True) for case in self.cases]
        variants = [list(reversed(good)),
                    [dict(row, sha256='x'*64) if i==2 else row for i,row in enumerate(good)],
                    [dict(row, cleanupErrors=['owned process live']) if i==2 else row for i,row in enumerate(good)],
                    [dict(row, module='wrong') if i==2 else row for i,row in enumerate(good)]]
        for rows in variants:
            with self.subTest(rows=rows[0]['case']):
                self.assertFalse(smoke.summarize(rows, self.suite)['passed'])

    def test_success_requires_two_engine_generations_normal_cleanup_and_final_container(self):
        case=self.cases[0]
        engines=[]
        class Engine:
            def __init__(self,suite):
                self.cleanup_errors=[]; self.closed=False; self.cleaned=False; engines.append(self)
                self.cleanup_evidence=successful_cleanup(suite)
            def start(self): pass
            def load(self,url): return object()
            def store_new(self,document,path,filter_name):
                with zipfile.ZipFile(path,'x') as package:
                    package.writestr('mimetype','application/vnd.oasis.opendocument.text')
                    package.writestr('content.xml','<document/>')
            def close_document(self,document): self.closed=True
            def cleanup(self): self.cleaned=True
        def reopen(engine, current, path):
            self.assertEqual(2,len(engines))
            self.assertTrue(engines[0].closed and engines[0].cleaned)
            self.assertIsNot(engines[0],engine)
            return object()
        with patch.object(smoke,'Engine',Engine), patch.object(smoke,'populate',return_value={}), \
             patch.object(smoke,'observe',return_value=smoke.expected(case)), patch.object(smoke,'load_saved',side_effect=reopen):
            row=smoke.run_case(self.suite,self.output,case)
        self.assertEqual('passed',row['status'],row)
        self.assertTrue(row['independentReopenVerified'])
        self.assertTrue(all(e.closed and e.cleaned for e in engines))
        self.assertEqual(64,len(row['sha256']))
        self.assertIn('engineCleanups',row,'Each new feature engine generation must retain its cleanup proof')
        self.assertEqual([item['phase'] for item in row['engineCleanups']],['create','independent-reopen'])

    def test_load_saved_is_readonly_macro_disabled_and_exact_filter_options(self):
        for case in (self.cases[4],self.cases[8]):
            observed={}
            def load(url,target,flags,properties):
                observed.update(properties)
                return object()
            engine=SimpleNamespace(prop=lambda name,value:(name,value),desktop=SimpleNamespace(loadComponentFromURL=load))
            with patch.dict(sys.modules, {'dispatch': SimpleNamespace(make_interaction_handler=lambda: 'abort')}):
                smoke.load_saved(engine,case,self.root/('generated.'+case['extension']))
            self.assertTrue(observed['ReadOnly'])
            self.assertEqual(0,observed['MacroExecutionMode'])
            self.assertEqual(0,observed['UpdateDocMode'])
            self.assertEqual(case['filter'],observed['FilterName'])
            self.assertEqual(smoke.TEXT_OPTIONS if case['extension']=='txt' else smoke.CSV_OPTIONS,observed['FilterOptions'])

    def test_crud_performs_real_committed_and_rolled_back_sql_transitions(self):
        db=self.root/'transaction.db'
        class Result:
            def __init__(self,cursor): self.cursor=cursor; self.iterator=iter(cursor.fetchall()); self.row=None
            def next(self):
                self.row=next(self.iterator,None); return self.row is not None
            def getInt(self,index): return int(self.row[index-1])
            def getString(self,index): return self.row[index-1]
            def close(self): self.cursor.close()
        class Statement:
            def __init__(self,connection,sql=None): self.connection=connection; self.sql=sql; self.values={}
            def execute(self,sql): self.connection.execute(sql)
            def close(self): pass  # SQLite cursors are owned and closed by Result.
            def executeQuery(self,sql): return Result(self.connection.execute(sql))
            def setInt(self,index,value): self.values[index]=value
            setString=setInt
            def executeUpdate(self,sql=None):
                return self.connection.execute(sql or self.sql,tuple(self.values[i] for i in sorted(self.values))).rowcount
        class Connection:
            def __init__(self): self.connection=sqlite3.connect(db)
            def setAutoCommit(self,value): pass
            def createStatement(self): return Statement(self.connection)
            def prepareStatement(self,sql): return Statement(self.connection,sql)
            def commit(self): self.connection.commit()
            def rollback(self): self.connection.rollback()
            def close(self): self.connection.close()
        document=SimpleNamespace(DataSource=SimpleNamespace(getIsolatedConnection=lambda user,password:Connection()))
        states=smoke._base_crud(document)
        self.assertEqual([1,2],[row['id'] for row in states['initialRows']])
        self.assertEqual(smoke.base_rows(True),states['committedRows'])
        self.assertEqual(states['committedRows'],states['rolledBackRows'])
        connection=sqlite3.connect(db)
        try:
            actual=connection.execute('SELECT ID,TEXT_VALUE,AMOUNT FROM OPENGEUL_SMOKE ORDER BY ID').fetchall()
        finally:
            # A sqlite connection context commits/rolls back but does not close.
            # Windows forbids deleting the owned fixture until this handle closes.
            connection.close()
        self.assertEqual([(row['id'],row['text'],row['amount']) for row in smoke.base_rows(True)],actual)

    def test_base_read_error_remains_primary_after_document_and_owned_cleanup_failures(self):
        case=next(case for case in self.cases if case['id']=='format-base-odb');events=[]
        primary=ValueError('original Base read error');document_error=OSError('document close failed')
        class Engine:
            def __init__(self,suite):
                self.cleanup_errors=[];self.cleanup_evidence=successful_cleanup(suite)
            def start(self):pass
            def service(self,name):return SimpleNamespace(initNew=lambda:None,DataSource=SimpleNamespace(setPropertyValue=lambda *args:None))
            def close_document(self,document):
                events.append('document.close');raise document_error
            def cleanup(self):
                events.append('owned.cleanup');self.cleanup_errors.append('forced job remains a failure')
        with patch.object(smoke,'Engine',Engine),patch.object(smoke,'store_new'),patch.object(smoke,'populate',return_value={}), \
             patch.object(smoke,'observe',side_effect=primary):
            row=smoke.run_case(self.suite,self.output,case)
        self.assertEqual(events,['document.close','owned.cleanup'])
        self.assertEqual(row['status'],'failed');self.assertEqual(row['error']['type'],'ValueError')
        self.assertEqual(row['error']['message'],'original Base read error')
        self.assertTrue(any('document close failed' in e for e in row['cleanupErrors']))
        self.assertTrue(any('forced job' in e for e in row['cleanupErrors']))
        self.assertIn('owned cleanup',row['error']['traceback'])
        self.assertIn(document_error,[error for stage,error in primary.base_cleanup_errors])

    def test_partial_results_preserved_and_next_case_runs_after_exception(self):
        seen=[]
        def run(case):
            seen.append(case['id'])
            if len(seen)==1: raise RuntimeError('first module failed')
            self.assertTrue((self.output/(self.cases[0]['id']+'.json')).exists())
            partial=json.loads((self.output/'office-features.json').read_text())
            self.assertEqual(1, len(partial['cases']))
            return dict(case=case['id'], status='passed', guiVerified=False)
        with redirect_stdout(io.StringIO()):
            report=smoke.run_all(self.cases[:2], run, self.output, self.suite)
        self.assertEqual(2,len(seen))
        self.assertFalse(report['passed'])
        self.assertEqual('RuntimeError', report['cases'][0]['error']['type'])
        self.assertTrue((self.output/(self.cases[1]['id']+'.json')).exists())

    def test_output_rejects_payload_child_existing_fixture_and_linked_parent(self):
        with self.assertRaises(ValueError): smoke.prepare_output(self.suite, self.suite/'bad')
        with self.assertRaises(FileExistsError): smoke.prepare_output(self.suite, self.output)
        link=self.root/'linked'
        try: link.symlink_to(self.output, target_is_directory=True)
        except (OSError, NotImplementedError): return
        with self.assertRaises(ValueError): smoke.prepare_output(self.suite, link/'new')

    def test_generated_fixture_requires_fixed_case_and_never_overwrites(self):
        case=self.cases[0]
        path=smoke.fixture_path(self.output,case)
        path.write_bytes(b'owned')
        with self.assertRaises(FileExistsError): smoke.fixture_path(self.output,case)
        bad=dict(case,id='../escape')
        with self.assertRaises(ValueError): smoke.fixture_path(self.output,bad)

    def test_missing_reopen_cleanup_and_final_hash_never_pass(self):
        case=self.cases[0]
        def fake_engine_factory(cleanup_error=False, erase=False, missing_proof=False):
            saved=[]
            generations=[]
            class Engine:
                def __init__(self,suite):
                    self.cleanup_errors=[]; self.cleanup_evidence=successful_cleanup(suite); generations.append(self)
                def start(self): pass
                def load(self,url): return object()
                def store_new(self,document,path,filter_name):
                    saved.append(path)
                    with zipfile.ZipFile(path,'x') as package:
                        package.writestr('mimetype','application/vnd.oasis.opendocument.text')
                        package.writestr('content.xml','<document/>')
                def close_document(self,document): pass
                def cleanup(self):
                    if cleanup_error: self.cleanup_errors.append('owned process still alive')
                    if missing_proof: self.cleanup_evidence=None
                    if erase and len(generations)==2: saved[0].unlink()
            return Engine
        for reason in ('cleanup','reopen','hash','proof'):
            with self.subTest(reason=reason):
                out=self.output/reason
                (out/'fixtures').mkdir(parents=True)
                observed=smoke.expected(case)
                with patch.object(smoke,'Engine',fake_engine_factory(reason=='cleanup',reason=='hash',reason=='proof')), \
                     patch.object(smoke,'populate',return_value={}), \
                     patch.object(smoke,'observe',return_value=observed), \
                     patch.object(smoke,'load_saved',side_effect=RuntimeError('reopen failed') if reason=='reopen' else None,return_value=object()):
                    row=smoke.run_case(self.suite,out,case)
                self.assertEqual('failed',row['status'])
                self.assertNotIn('sha256',row)
                self.assertFalse(row['guiVerified'])
                if reason=='reopen': self.assertEqual('reopen failed',row['error']['message'])
                elif reason=='hash': self.assertEqual('FileNotFoundError',row['error']['type'])
                elif reason=='proof': self.assertIn('cleanup evidence',row['error']['message'])
                else: self.assertIn('owned process still alive',row['cleanupErrors'])

    def test_manifest_filter_drift_is_setup_failure(self):
        modules=json.loads((SOURCE.parents[1]/'config/product.json').read_text())['modules']
        smoke.validate_modules(modules)
        for mutate in ('missing','filter','factory','extra'):
            changed=copy.deepcopy(modules)
            if mutate=='missing': del changed['writer']['filters']['odt']
            elif mutate=='filter': changed['writer']['filters']['odt']='wrong'
            elif mutate=='factory': changed['writer']['factory']='http://remote'
            else: changed['writer']['filters']['unknown']='invented'
            with self.assertRaises(ValueError): smoke.validate_modules(changed)


if __name__=='__main__': unittest.main()
