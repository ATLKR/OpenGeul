"""Finite canonical normal-case IMM projection; no live Windows observation."""
import copy
import importlib.util
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'e2e'))
import test_korean_ime_smoke as typed_fixtures

SOURCE=Path(__file__).resolve().parents[1]/'e2e/ime_mode_summary.py'


def admitted_record():
    original=typed_fixtures.KoreanImePolicyTests().record()
    record={key:original[key] for key in ('module','windowHwnd','childHwnd','officePid','editorTid',
        'keyboardFocusHwnd','readiness','imeCommands','imePolicyVersion','case')}
    record.update(kind='native-korean-ime',shellPid=77,parentHwnd=12,architecture='x64')
    image='C:/Synthetic Suite/Office/program/soffice.bin'
    binding=dict(shellPid=77,officePid=31,shellCreationTime=1000,officeCreationTime=2000,expectedImage=image,
        suiteHwnd=11,parentHwnd=12,childHwnd=22,rootHwnd=11)
    record['imeKeyboardSession']=dict(schemaVersion=1,kind='owned-first-admission-ime-keyboard',expectedNative=binding,
        originalEngine=dict(pid=31,creationTime=2000,image=image,handleValue=202,waitResult=258),
        originalShell=dict(pid=77,creationTime=1000,image='C:/Synthetic Suite/OpenGeul.Office.exe',handleValue=201,waitResult=258))
    rows=[]
    for index,(ack,context,conversion_ok,opened,conversion) in enumerate((
            (2,1,1,1,0),(3,1,1,1,33),(3,1,1,0,33),(3,1,1,1,32),(3,0,0,0,0),(3,1,1,1,1)),1):
        rows.append(dict(sequence=index,message=0x282,origin=1,pid=31,tid=41,commandAck=ack,hwnd=51,
            layout=record['imeCommands'][2]['layout'],wparam=0,lparam=0,focusHwnd=51,counter=1000+index,
            immContextPresent=context,immConversionSucceeded=conversion_ok,immOpen=opened,
            immConversion=conversion,immSentence=0,himc=4096))
    record['imeMessageDiagnostics']=dict(schemaVersion=1,kind='passive-owned-ime-messages',status='complete',
        capacity=128,observedCount=len(rows),events=rows)
    return record


def implementation():
    assert SOURCE.is_file(),'Canonical pre-restoration IMM summary projector is required'
    spec=importlib.util.spec_from_file_location('ime_mode_summary_under_test',SOURCE)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


class IMEModeSummaryTests(unittest.TestCase):
    def test_counts_only_valid_post_ack_native_context_samples(self):
        record=admitted_record();before=copy.deepcopy(record)
        self.assertEqual(implementation().project(record),dict(imeModeSamples=4,imeModeClosed=1,imeModeAlpha=1,
            imeLastOpen=1,imeLastNative=1))
        self.assertEqual(record,before)

    def test_missing_or_incomplete_capture_remains_unknown(self):
        for damage in ('missing','empty','partial','overflow','count','capacity','extra','no-post','no-valid'):
            record=admitted_record();capture=record['imeMessageDiagnostics']
            if damage=='missing':record.pop('imeMessageDiagnostics')
            elif damage=='empty':capture.update(events=[],observedCount=0)
            elif damage in ('partial','overflow'):capture['status']=damage
            elif damage=='count':capture['observedCount']+=1
            elif damage=='capacity':capture['capacity']=129
            elif damage=='extra':capture['unbound']=1
            elif damage=='no-post':
                for row in capture['events']:row['commandAck']=2
            elif damage=='no-valid':
                for row in capture['events']:row.update(immContextPresent=0,immConversionSucceeded=0)
            with self.subTest(damage=damage):self.assertIsNone(implementation().project(record))

    def test_original_command_ack_mode_profile_and_generation_are_required(self):
        for damage in ('ack','published','status','snapshot','attempt','duplicate','context','profile','typed','imm',
                       'source','source-arch','engine-generation','engine-handle','shell','case','normal-kind'):
            record=admitted_record();command=record['imeCommands'][2]
            if damage=='ack':command['nativeAck']=2
            elif damage=='published':command['publishedCommand']=4
            elif damage=='status':command['status']=-41
            elif damage=='snapshot':command['snapshotEvidence']['stable']=False
            elif damage=='attempt':command['nativeAttemptedMask']=15
            elif damage=='duplicate':record['imeCommands'].insert(2,copy.deepcopy(command))
            elif damage=='context':command['nativeContext']['targetHwnd']+=1
            elif damage=='profile':command['activeProfile']='{00000000-0000-0000-0000-000000000000}'
            elif damage=='typed':command['threadMode']['afterOpenType']=0
            elif damage=='imm':command['immState']['open']=0
            elif damage=='source':record['readiness']['source']['sourceCommit']='unbound'
            elif damage=='source-arch':record['readiness']['source']['architecture']='arm64'
            elif damage=='engine-generation':record['imeKeyboardSession']['originalEngine']['creationTime']+=1
            elif damage=='engine-handle':record['imeKeyboardSession']['originalEngine']['handleValue']=0
            elif damage=='shell':record['imeKeyboardSession']['originalShell']['pid']+=1
            elif damage=='case':record['case']='ime-impress'
            elif damage=='normal-kind':record['kind']='native-ime-mode-diagnostic'
            with self.subTest(damage=damage):self.assertIsNone(implementation().project(record))

    def test_foreign_reordered_restore_or_malformed_rows_do_not_become_mode_evidence(self):
        for damage in ('pid','tid','hwnd','focus','layout','order','counter','ack-order','restore','oversized','bool','extra'):
            record=admitted_record();capture=record['imeMessageDiagnostics'];row=capture['events'][2]
            if damage in ('pid','tid','hwnd','focus','layout'):
                key='focusHwnd' if damage=='focus' else damage
                row[key]+=1
            elif damage=='order':row['sequence']+=1
            elif damage=='counter':row['counter']=1
            elif damage=='ack-order':capture['events'][-1]['commandAck']=2
            elif damage=='restore':capture['events'][-1]['commandAck']=4
            elif damage=='oversized':capture.update(events=capture['events']*22,observedCount=132)
            elif damage=='bool':row['immOpen']=False
            elif damage=='extra':row['unbound']=1
            with self.subTest(damage=damage):self.assertIsNone(implementation().project(record))

    def test_last_flags_are_from_last_valid_sample_only(self):
        record=admitted_record();rows=record['imeMessageDiagnostics']['events']
        rows[-1].update(immOpen=0,immConversion=0)
        self.assertEqual(implementation().project(record),dict(imeModeSamples=4,imeModeClosed=2,imeModeAlpha=1,
            imeLastOpen=0,imeLastNative=0))
        rows[-1].update(immContextPresent=0,immConversionSucceeded=0)
        self.assertEqual(implementation().project(record),dict(imeModeSamples=3,imeModeClosed=1,imeModeAlpha=1,
            imeLastOpen=1,imeLastNative=0))

    def test_payload_and_himc_values_are_never_read_or_exported(self):
        class Unreadable:
            def __bool__(self):raise AssertionError('Payload read')
            def __int__(self):raise AssertionError('Payload read')
            def __eq__(self,other):raise AssertionError('Payload read')
            def __repr__(self):raise AssertionError('Payload read')
        record=admitted_record()
        for row in record['imeMessageDiagnostics']['events']:
            for key in ('message','wparam','lparam','himc','immSentence'):row[key]=Unreadable()
        for key in ('events','keyTokens','savedText','reopened','asciiPrefix','imeModeSummary'):record[key]=Unreadable()
        projected=implementation().project(record)
        self.assertEqual(set(projected),{'imeModeSamples','imeModeClosed','imeModeAlpha','imeLastOpen','imeLastNative'})
        self.assertTrue(all(type(value) is int for value in projected.values()))
        self.assertEqual(projected['imeModeSamples'],4)
