"""Require all actual print scenarios, preserve bounded JSON/JUnit evidence."""
import json,os,sys,unittest
from pathlib import Path
import xml.etree.ElementTree as ET
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from run import EvidenceResult
from test_print import PrintingTests

def main():
    output=Path(os.environ['PRINT_OUTPUT']);output.mkdir(parents=True,exist_ok=True)
    result=unittest.TextTestRunner(verbosity=2,resultclass=EvidenceResult).run(unittest.defaultTestLoader.loadTestsFromTestCase(PrintingTests))
    ok=result.wasSuccessful() and result.testsRun==8 and not result.skipped
    payload={'commit':os.environ.get('GITHUB_SHA'),'runId':os.environ.get('GITHUB_RUN_ID'),
        'payloadRun':os.environ.get('PRINT_PAYLOAD_RUN',os.environ.get('GITHUB_RUN_ID')),
        'tests':result.records,'expectedTests':8,'success':ok}
    (output/'results.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
    xml=ET.Element('testsuite',name='OpenGeul virtual printer',tests=str(result.testsRun),failures=str(len(result.failures)),errors=str(len(result.errors)),skipped=str(len(result.skipped)))
    for rec in result.records:
        case=ET.SubElement(xml,'testcase',name=rec['test'],time=str(rec['seconds']))
        if rec['status']!='passed':ET.SubElement(case,{'failed':'failure','error':'error','skipped':'skipped'}[rec['status']]).text=rec['message']
    # Include setup/cleanup errors, which don't have a stopTest record.
    if len(result.errors)>sum(r['status']=='error' for r in result.records):
        for test,msg in result.errors:
            if not any(r['test']==test.id() for r in result.records):
                ET.SubElement(ET.SubElement(xml,'testcase',name=test.id()),'error').text=msg
    ET.ElementTree(xml).write(output/'junit.xml',encoding='utf-8',xml_declaration=True)
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'],'a',encoding='utf-8') as f:
            f.write(f'## Actual Microsoft PDF printer\n{result.testsRun}/8 cases; failures {len(result.failures)}, errors {len(result.errors)}, skips {len(result.skipped)}. Success: {ok}.\n')
    return 0 if ok else 1
if __name__=='__main__':sys.exit(main())
