from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET


def inspect(report: Path, identity: str, version: str, exit_code: int) -> dict:
    result={'status':'failed','passed':False,'submissionCheckPassed':False,'exitCode':exit_code,'expectedIdentity':identity,
            'expectedVersion':version,'scope':'Windows App Certification Kit, not Microsoft Store approval'}
    try:
        if report.stat().st_size > 6*1024*1024:raise ValueError('WACK XML exceeds the evidence limit')
        data=report.read_bytes()
        if b'<!DOCTYPE' in data.upper() or b'<!ENTITY' in data.upper():raise ValueError('Unsupported XML declarations')
        root=ET.fromstring(data)
        if root.tag != 'REPORT':raise ValueError('Expected WACK REPORT XML')
        result.update(overallResult=root.get('OVERALL_RESULT'),partialRun=root.get('PARTIAL_RUN'),
                      identity=root.get('APP_NAME'),version=root.get('APP_VERSION'),
                      appType=root.get('APP_TYPE'),
                      kitVersion=root.get('VERSION'),reportTime=root.get('ReportGenerationTime'),
                      reportSha256=hashlib.sha256(data).hexdigest())
        tests=list(root.iter('TEST'))
        result['nonPassingTests']=[{'name':test.get('NAME'),'result':test.findtext('RESULT','').strip(),
                                   'optional':test.get('OPTIONAL') == 'TRUE',
                                   'messages':[message.get('TEXT',''.join(message.itertext()))
                                               for message in test.findall('./MESSAGES/MESSAGE')]}
                                  for test in tests if test.findtext('RESULT','').strip() != 'PASS']
        if root.get('APP_TYPE') == 'Centennial':
            programs=root.findall("./APPLICATIONS/Installed_Programs/Program[@Source='AppxPackage']")
            if len(programs) != 1:raise ValueError('Expected one Centennial AppxPackage program')
            program=programs[0]
            identities=program.findall('./Indicators/WindowsStoreAppManifestIndicators/PackageManifest/Package/Identity')
            if len(identities) != 1:raise ValueError('Expected one embedded Centennial package identity')
            embedded=identities[0]
            name=embedded.get('Name');package_version=embedded.get('Version')
            if (name != identity or package_version != version or program.get('Name') != name
                    or program.get('Version') != package_version
                    or root.get('APP_NAME') not in (None,'',name)
                    or root.get('APP_VERSION') not in (None,'',package_version)):
                raise ValueError('Centennial report identities or versions do not match the candidate')
            result.update(identity=name,version=package_version)
        complete=(exit_code == 0 and root.get('PARTIAL_RUN') == 'FALSE'
                  and bool(root.get('VALIDATION_TYPE','').strip())
                  and result['identity'] == identity and result['version'] == version
                  and bool(tests) and all(test.get('NAME') and len(test.findall('RESULT')) == 1
                                         and len(test.find('RESULT')) == 0 and test.findtext('RESULT','').strip()
                                         in ('PASS','FAIL','WARNING') for test in tests))
        required=[test for test in tests if test.get('OPTIONAL') != 'TRUE']
        required_pass=bool(required) and all(test.findtext('RESULT','').strip() == 'PASS' for test in required)
        result['passed']=(complete and required_pass and root.get('OVERALL_RESULT') == 'PASS'
                          and not result['nonPassingTests'])
        result['submissionCheckPassed']=(result['passed'] or (complete and required_pass
                                        and root.get('APP_TYPE') == 'Centennial'
                                        and root.get('OVERALL_RESULT') in ('PASS','WARNING')))
        if result['passed']:result['status']='passed'
        elif result['submissionCheckPassed']:
            result.update(status='warning',reason='Required Centennial tests passed; optional findings remain. This is not a complete WACK PASS or Microsoft Store approval.')
        else:result['reason']='WACK did not produce a complete passing required-test check for this package identity and version'
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
    if result['passed']:
        print('WACK XML reports a complete PASS for the tested package identity and version.')
        return
    if result['submissionCheckPassed']:
        print('::warning::'+result['reason'])
        for test in result['nonPassingTests']:
            message='\n'.join([f"{test['name']}: {test['result']}"]+test['messages'])
            print('::warning::'+message.replace('%','%25').replace('\r','%0D').replace('\n','%0A'))
    raise SystemExit(result['reason'])


if __name__=='__main__':main()
