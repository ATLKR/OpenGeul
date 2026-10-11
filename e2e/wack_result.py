from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET


def inspect(report: Path, identity: str, version: str, exit_code: int) -> dict:
    result={'status':'failed','passed':False,'exitCode':exit_code,'expectedIdentity':identity,
            'expectedVersion':version,'scope':'Windows App Certification Kit, not Microsoft Store approval'}
    try:
        if report.stat().st_size > 6*1024*1024:raise ValueError('WACK XML exceeds the evidence limit')
        data=report.read_bytes()
        if b'<!DOCTYPE' in data.upper() or b'<!ENTITY' in data.upper():raise ValueError('Unsupported XML declarations')
        root=ET.fromstring(data)
        if root.tag != 'REPORT':raise ValueError('Expected WACK REPORT XML')
        result.update(overallResult=root.get('OVERALL_RESULT'),partialRun=root.get('PARTIAL_RUN'),
                      identity=root.get('APP_NAME'),version=root.get('APP_VERSION'),
                      kitVersion=root.get('VERSION'),reportTime=root.get('ReportGenerationTime'),
                      reportSha256=hashlib.sha256(data).hexdigest())
        result['nonPassingTests']=[{'name':test.get('NAME'),'result':test.findtext('RESULT')}
                                   for test in root.iter('TEST') if test.findtext('RESULT','').strip() != 'PASS']
        result['passed']=(exit_code == 0 and root.get('OVERALL_RESULT') == 'PASS'
                          and root.get('PARTIAL_RUN') == 'FALSE' and bool(root.get('VALIDATION_TYPE'))
                          and root.get('APP_NAME') == identity and root.get('APP_VERSION') == version)
        if result['passed']:result['status']='passed'
        else:result['reason']='WACK did not produce a complete PASS for this package identity and version'
    except (OSError,ValueError,ET.ParseError) as error:
        result['reason']=str(error)
    return result


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--report',type=Path,required=True);parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--identity',required=True);parser.add_argument('--version',required=True)
    parser.add_argument('--exit-code',type=int,required=True)
    args=parser.parse_args();result=inspect(args.report,args.identity,args.version,args.exit_code)
    args.out.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    if not result['passed']:raise SystemExit(result['reason'])
    print('WACK XML reports a complete PASS for the tested package identity and version.')


if __name__=='__main__':main()
