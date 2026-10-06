"""Fail-closed E2E entrypoint with JSON and JUnit evidence; no automatic flaky retries."""
import json
import os
from pathlib import Path
import sys
import time
import unittest
import xml.etree.ElementTree as ET

class EvidenceResult(unittest.TextTestResult):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs);self.records=[];self.started={};self.status={}
    def startTest(self,test):self.started[test.id()]=time.monotonic();super().startTest(test)
    def addSuccess(self,test):self.status[test.id()]=('passed','');super().addSuccess(test)
    def addFailure(self,test,err):self.status[test.id()]=('failed',self._exc_info_to_string(err,test));super().addFailure(test,err)
    def addError(self,test,err):self.status[test.id()]=('error',self._exc_info_to_string(err,test));super().addError(test,err)
    def addSkip(self,test,reason):self.status[test.id()]=('skipped',reason);super().addSkip(test,reason)
    def stopTest(self,test):
        status,message=self.status.get(test.id(),('error','No result recorded'))
        self.records.append({'test':test.id(),'status':status,'seconds':round(time.monotonic()-self.started[test.id()],3),'message':message})
        super().stopTest(test)

def main():
    output=Path(os.environ['E2E_OUTPUT']);output.mkdir(parents=True,exist_ok=True)
    from test_hop_followups import suite
    result=unittest.TextTestRunner(verbosity=2,resultclass=EvidenceResult).run(suite())
    expected=16 if os.environ.get('E2E_MODE')=='native' else 10
    payload={'commit':os.environ.get('GITHUB_SHA'),'runId':os.environ.get('GITHUB_RUN_ID'),'mode':os.environ.get('E2E_MODE'),
        'browser':os.environ.get('E2E_BROWSER'),'os':os.environ.get('RUNNER_OS'),'tests':result.records,
        'expectedTests':expected,'success':result.wasSuccessful() and not result.skipped and result.testsRun==expected}
    (output/'results.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
    xml=ET.Element('testsuite',name='OpenGeul E2E',tests=str(result.testsRun),failures=str(len(result.failures)),errors=str(len(result.errors)),skipped=str(len(result.skipped)))
    for record in result.records:
        case=ET.SubElement(xml,'testcase',name=record['test'],time=str(record['seconds']))
        if record['status']!='passed':ET.SubElement(case,{'failed':'failure','error':'error','skipped':'skipped'}[record['status']]).text=record['message']
    ET.ElementTree(xml).write(output/'junit.xml',encoding='utf-8',xml_declaration=True)
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'],'a',encoding='utf-8') as stream:
            stream.write(f"## {payload['mode']} / {payload['browser']} E2E\nTests: {result.testsRun}; failures: {len(result.failures)}; errors: {len(result.errors)}; skips: {len(result.skipped)}.\n")
    return 0 if payload['success'] else 1

if __name__=='__main__':sys.exit(main())
