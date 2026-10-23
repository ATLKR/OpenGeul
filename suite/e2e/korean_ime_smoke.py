"""Real Microsoft Korean IME composition in owned Suite Writer/Calc/Impress frames.

Unlike Unicode keyboard injection, physical Dubeolsik scan codes must produce
in-process WM_IME_COMPOSITION receipts, survive Backspace, save and UNO reopen.
The observer is a temporary native DLL hooked only into the owned editor thread.
"""
from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes as W
import hashlib
import json
import mmap
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import uuid

from windows_smoke import (Windows, INPUT_CASES, capture_failure, close_document,
    close_home, collect_cases, launch_suite, activate_owned_suite, package_text, require_engine_fixture,
    stop_owned_test_process, verified_attachment, wait_for, write_result, ascii_input)
from engine_smoke import verify_content
import native_suite_architecture as native_arch
import ime_thread_mode as native_mode
from ime_keyboard_session import IMEKeyboardSession
from ime_calc_setup import observe_calc_setup
from ime_semantic_context import observe_ime_semantic_setup

EXPECTED_KEYS = list('gksrmf') + ['BACKSPACE', 'f', 'RIGHT']
SCANS = dict(zip('qwertyuiopasdfghjklzxcvbnm',
    (0x10, 0x11, 0x12, 0x13, 0x14, 0x15, 0x16, 0x17, 0x18, 0x19,
     0x1e, 0x1f, 0x20, 0x21, 0x22, 0x23, 0x24, 0x25, 0x26,
     0x2c, 0x2d, 0x2e, 0x2f, 0x30, 0x31, 0x32)))
SCANS.update(BACKSPACE=0x0e, RIGHT=0xe04d)


def scan_events(tokens):
    if not isinstance(tokens, (list, tuple)) or not 1 <= len(tokens) <= 64:
        raise ValueError('A bounded list of physical key names is required')
    result = []
    for token in tokens:
        if token not in SCANS: raise ValueError('Unsupported physical key: ' + str(token))
        scan = SCANS[token]
        flags = 8 | (1 if scan > 255 else 0)  # KEYEVENTF_SCANCODE, EXTENDEDKEY
        result.extend(({'vk': 0, 'scan': scan & 255, 'flags': flags},
                       {'vk': 0, 'scan': scan & 255, 'flags': flags | 2}))
    return result


def require_readiness(record, *, architecture='x64'):
    native_arch.require_architecture(architecture)
    assert isinstance(record, dict) and record.get('suiteOnly') is True, 'Suite-only readiness is required'
    assert record.get('capabilityAfter') == 'Installed' and record.get('restartNeeded') is False, 'Korean Basic must be Installed without pending restart'
    assert record.get('userLanguageConfigured') is True, 'Current CI user has no configured Korean input profile'
    profile = record.get('profile', {})
    guid = r'\{[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}\}'
    assert profile.get('registered') is True and re.fullmatch('0412:' + guid + guid, profile.get('inputTip', '')), 'A registered native Korean TSF profile is required'
    assert profile.get('inputTip') == '0412:' + profile.get('providerClsid', '') + profile.get('profileGuid', ''), 'Registered TSF identity differs from its configured input tip'
    machine = native_arch.NATIVE_MACHINES[architecture]
    assert type(record.get('nativeMachine')) is int and record['nativeMachine'] == machine, 'Korean readiness native OS architecture differs from Suite'
    if architecture == 'arm64' or 'controllerMachine' in record:
        assert type(record.get('controllerMachine')) is int and record['controllerMachine'] == 0, 'Korean readiness controller must be native'
    if architecture == 'arm64' or 'architecture' in record.get('source', {}):
        assert record.get('source', {}).get('architecture') == architecture, 'Korean readiness source architecture differs from Suite'
    component = profile.get('component', {})
    assert (component.get('signatureStatus') == 'Valid' and type(component.get('machine')) is int
            and component['machine'] == machine), 'Native ' + architecture + ' Microsoft IME identity is unverified'
    assert re.fullmatch('[0-9a-f]{64}', component.get('sha256', '')), 'IME component digest is missing'
    assert re.search(r'(?:^|,\s*)O=Microsoft Corporation(?:,|$)', component.get('signerSubject', '')), 'IME component is not signed by Microsoft'
    return record


def marker(module):
    assert module in dict(INPUT_CASES)
    # Keep the ASCII prefix literal in the IME's alphanumeric mode, without
    # relying on synthetic implicit Shift state. Saved XML and UNO must match.
    return 'ime-opengeul-' + module + ':한글'


def activate_after_ascii_prefix(observer, module, record, send_ascii):
    prepare_ascii_prefix(observer, module, record, send_ascii)
    return observer.command(1)


def prepare_ascii_prefix(observer, module, record, send_ascii):
    # The marker scaffold belongs to setup, before switching input language or
    # IME conversion mode. Only the Hangul below is typed through Korean IME.
    record['stage'] = 'type-ascii-prefix-before-ime'
    observer.require_target()
    layout = int(observer.api.user.GetKeyboardLayout(observer.tid) or 0)
    assert layout & 0xffff == 0x0409, 'ASCII setup requires the verified original English input layout'
    assert not record.get('asciiEditorInputs'), 'IME ASCII setup requires one fresh counted input receipt'
    prefix = ' ' + marker(module).split('한글')[0]
    send_ascii(prefix)
    record.update(asciiPrefix=prefix, prefixInputLayout=layout,
                  stage='activate-microsoft-korean-profile')
    require_ascii_prefix(record)
    return prefix


def require_ascii_prefix(record):
    """Replay the one physical setup receipt before allowing Korean activation."""
    expected = ' ' + marker(record['module']).split('한글')[0]
    assert record.get('asciiPrefix') == expected and record.get('prefixInputLayout') == ascii_input.US_LAYOUT, 'IME ASCII setup requires its exact prefix on the original US layout'
    receipts = record.get('asciiEditorInputs')
    assert isinstance(receipts, list) and len(receipts) == 1, 'IME ASCII setup requires exactly one counted physical receipt'
    for key in ('windowHwnd', 'childHwnd', 'keyboardFocusHwnd', 'editorTid'):
        assert type(record.get(key)) is int and record[key] > 0, 'IME ASCII setup has no owned editor identity'
    receipt = ascii_input.require_ascii_receipt(receipts[0], expected, record['windowHwnd'], record['childHwnd'])
    assert receipt.get('pauseSeconds') == 0.04, 'IME ASCII setup must retain its original character pacing'
    for action in receipt['actions']:
        for side in ('before', 'after'):
            snapshot = action[side]
            assert snapshot['focusHwnd'] == record['keyboardFocusHwnd'] and snapshot['editorThreadId'] == record['editorTid'], 'IME ASCII setup differs from the observed editor focus/thread'
    return receipt


def validate_restoration(receipt):
    assert isinstance(receipt, dict) and receipt.get('command') == 4 and receipt.get('status') == 0, 'Native restoration command did not succeed'
    assert all(receipt.get(key) == 0 for key in ('profileManagerHresult', 'previousProfileHresult', 'activateProfileHresult', 'activeProfileHresult', 'activateLayoutError')), 'Native restoration API failed or its result is missing'
    assert receipt.get('previousLayout', 0) and receipt.get('layout') == receipt['previousLayout'], 'Original owned-thread HKL was not restored'
    assert receipt.get('previousProfileType') in (1, 2) and receipt.get('previousLanguage', 0), 'Original TSF identity was not captured'
    guid = r'\{[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}\}'
    for previous, active in (('previousProfileType', 'activeProfileType'), ('previousLanguage', 'activeLanguage'),
                             ('previousProfileLayout', 'activeProfileLayout')):
        assert previous in receipt and receipt.get(active) == receipt[previous], 'Original TSF profile was not restored'
    for previous, active in (('previousClsid', 'activeClsid'), ('previousProfile', 'activeProfile')):
        assert re.fullmatch(guid, receipt.get(previous, '')) and receipt.get(active, '').lower() == receipt[previous].lower(), 'Original TSF GUID identity was not restored'
    return receipt


def original_empty_us_profile(row):
    return (all(type(row.get(key)) is int and row[key] == value for key, value in
        (('previousLayout', 0x04090409), ('previousProfileType', 2), ('previousLanguage', 0x0409), ('previousProfileLayout', 0x04090409)))
        and all(type(row.get(key)) is str and row[key].lower() == '{00000000-0000-0000-0000-000000000000}' for key in ('previousClsid', 'previousProfile')))


def require_mode_context(row):
    context = row['nativeContext']
    assert type(row.get('policyVersion')) is int and row['policyVersion'] == 4
    assert type(context) is dict and set(context) == {'magic', 'version', 'pid', 'tid', 'targetHwnd', 'rootHwnd'}
    assert all(type(value) is int and 0 < value < 2**64 for value in context.values())
    assert context['magic'] == 0x4f47494d and context['version'] == 4 and context['pid'] < 2**32 and context['tid'] < 2**32, 'Native typed policy context/version changed'
    return tuple(context[key] for key in ('magic', 'version', 'pid', 'tid', 'targetHwnd', 'rootHwnd'))


def require_tsf_pipeline(record):
    """Replay wire4 values and every command; no EMPTY scalar or restoration alias."""
    assert type(record.get('imePolicyVersion')) is int and record['imePolicyVersion'] == 4
    commands = record['imeCommands']
    assert type(commands) is list and len(commands) == 4 and [row['command'] for row in commands] == [1, 2, 3, 4], 'Original one-shot TSF command pipeline is incomplete'
    assert record['activeProfile'] == commands[0] and record['restoration'] == commands[3]
    context = require_mode_context(commands[0])
    assert context[2:] == (record['officePid'], record['editorTid'], record['keyboardFocusHwnd'], record['windowHwnd']), 'Native TSF context differs from the original editor'
    original = native_mode.require_typed_mode_receipt(commands[0]['threadMode'], 1, allow_empty=original_empty_us_profile(commands[0]))
    origin = 'empty' if original[0][1] == 0 else 'i4'
    profile = require_readiness(record['readiness'], architecture=record.get('architecture', 'x64'))['profile']
    for sequence, row in enumerate(commands, 1):
        assert require_mode_context(row) == context
        assert type(row['startedAt']) in (int, float) and math.isfinite(row['startedAt']) and row['startedAt'] >= 0
        if sequence > 1: assert commands[sequence-2]['startedAt'] <= row['startedAt'], 'TSF command observation times moved backwards'
        for key in ('command', 'nativeAck', 'publishedCommand', 'nativeAttemptedMask', 'nativeCallAttempts', 'nativePublicationReturn', 'status', 'tsfModeCaptured', 'profileChangeAttempted'):
            assert type(row[key]) is int
        assert row['nativeAck'] == row['publishedCommand'] == sequence
        assert row['acknowledged'] is True and row['success'] is True and row['nativeCallAttempts'] == row['nativePublicationReturn'] == 1 and row['status'] == 0
        assert set(row['snapshotEvidence']) == {'copyReturn', 'ackBefore', 'ackAfter', 'stable'} and all(type(row['snapshotEvidence'][key]) is int for key in ('copyReturn', 'ackBefore', 'ackAfter'))
        assert row['snapshotEvidence'] == dict(copyReturn=1, ackBefore=sequence, ackAfter=sequence, stable=True)
        assert row['snapshotEvidence']['stable'] is True
        assert set(row['commandRejection']) == {'count', 'sequence', 'during', 'reason'} and all(type(value) is int for value in row['commandRejection'].values())
        assert row['nativeAttemptedMask'] == (1 << sequence)-1 and row['commandRejection'] == dict(count=0, sequence=0, during=0, reason=0)
        assert (row['modeDeadlineCounter'], row['modeCounterFrequency']) == (row['requestedBudget']['counter'], row['requestedBudget']['frequency'])
        assert all(type(row[key]) is int and 0 < row[key] < 2**63 for key in ('modeDeadlineCounter', 'modeCounterFrequency'))
        observed = native_mode.require_typed_mode_receipt(row['threadMode'], sequence, original=original if sequence != 1 else None, allow_empty=original_empty_us_profile(row) if sequence == 1 else False)
        expected_tags = native_mode.typed_pair_dict(observed)
        assert type(row['typedValues']) is dict and set(row['typedValues']) == set(expected_tags)
        for key, expected in expected_tags.items():
            actual = row['typedValues'][key]
            assert type(actual) is dict and set(actual) == set(expected) and all(type(actual[name]) is type(value) and actual[name] == value for name, value in expected.items()), 'Typed JSON tags differ from the exact raw receipt'
        assert row['tsfOrigin'] == origin
        assert row['tsfModeCaptured'] == row['profileChangeAttempted'] == 1
        for key in ('layout', 'previousLayout', 'previousProfileType', 'previousLanguage', 'previousProfileLayout', 'activeProfileType', 'activeProfileLayout', 'activeLanguage'):
            assert type(row[key]) is int and 0 <= row[key] < 2**64
        for key in ('profileManagerHresult', 'previousProfileHresult', 'activateProfileHresult', 'activeProfileHresult', 'activateLayoutError'):
            assert type(row[key]) is int and row[key] == 0
        assert row['previousImmState'] == commands[0]['previousImmState']
        assert set(row['previousImmState']) == {'open', 'conversion', 'sentence'}
        imm = row['immState']
        assert set(imm) == {'contextPresent', 'conversionSucceeded', 'open', 'conversion', 'sentence'}
        assert all(type(value) is int and 0 <= value < 2**32 for value in (*imm.values(), *row['previousImmState'].values()))
        assert imm['contextPresent'] == imm['conversionSucceeded'] == 1
        if sequence in (1, 2, 3):
            assert row['activeLanguage'] == 0x0412 and row['activeClsid'].lower() == profile['providerClsid'].lower() and row['activeProfile'].lower() == profile['profileGuid'].lower() and row['layout'] & 0xffff == 0x0412
        if sequence in (2, 3): assert imm['open'] and bool(imm['conversion'] & 1) == (sequence == 3), 'IMM mode did not acknowledge the exact TSF request'
    restored = commands[3]
    assert commands[0]['previousImmState'] == {key: commands[0]['immState'][key] for key in ('open', 'conversion', 'sentence')}, 'Original IMM capture metadata differs from its raw getters'
    validate_restoration(restored)
    assert {key: restored['immState'][key] for key in ('open', 'conversion', 'sentence')} == commands[0]['previousImmState'], 'Original IMM state did not return'
    facts = dict(profileHklRestored=True, immEqual=True,
        typedStateEqual=commands[0]['typedValues'] == restored['typedValues'],
        restorationDisposition='empty-origin-retirement-required' if origin == 'empty' else 'concrete-restored')
    assert all(restored.get(key) == value and type(restored.get(key)) is type(value) for key, value in facts.items()), 'Typed restoration disposition differs from raw observations'
    return origin, facts


def _require_precommand_retirement_join(record):
    admission = record['imeEngineRetirement']['admission']
    assert type(record['imeCommands'][0]['startedAt']) in (int, float) and math.isfinite(record['imeCommands'][0]['startedAt'])
    assert admission['finishedAt'] <= record['imeCommands'][0]['startedAt'], 'Independent engine HANDLE was not admitted before command1'
    assert record['imeKeyboardSession']['setupFinishedAt'] <= admission['startedAt'], 'Engine HANDLE admission predates the original completed setup'
    assert (admission['editorTid'], admission['focusHwnd']) == (record['editorTid'], record['keyboardFocusHwnd'])


def original_ime_profile(record):
    """Use the original POST reader's native directory witness, never the proof."""
    from writer_model_reader import canonical_profile_projection
    from ime_semantic_context import require_ime_semantic_context
    context = record['imeSemanticContext']
    keyboard = record['imeKeyboardSession']
    native = keyboard['expectedNative']
    deadline = record['imeSetupBudget']['deadline']
    assert context.get('success') is True and context.get('phase') == 'post'
    assert context['expectedNative'] == native and context['setupDeadline'] == deadline, 'Original semantic profile belongs to another setup/generation'
    # Replay at the retained historical completion anchor. Reopen/save time
    # cannot renew setup or manufacture a fresh native observation.
    require_ime_semantic_context(context,module=record['module'],expected_native=native,
        setup_deadline=deadline,now=context['finishedAt'],phase='post',expected_prefix=record['asciiPrefix'])
    readiness = keyboard['semanticReadiness']
    assert type(readiness) is list and len(readiness) == 2
    for row, phase, source in zip(readiness, ('pre', 'post'), (context['preContext'], context)):
        assert type(row) is dict and set(row) == {'phase', 'readerFinishedAt', 'readerDeadline', 'setupDeadline', 'acknowledgedAt'} and row['phase'] == phase
        assert all(type(row[key]) in (int, float) and math.isfinite(row[key]) and row[key] >= 0 for key in ('readerFinishedAt', 'readerDeadline', 'setupDeadline', 'acknowledgedAt'))
        assert (row['readerFinishedAt'], row['readerDeadline'], row['setupDeadline']) == (source['finishedAt'], source['readerDeadline'], deadline)
        assert row['readerFinishedAt'] <= row['acknowledgedAt'] < deadline
    assert readiness[0]['acknowledgedAt'] <= context['startedAt']
    finished = keyboard['setupFinishedAt']
    assert type(finished) in (int, float) and math.isfinite(finished) and readiness[-1]['acknowledgedAt'] <= finished < deadline, 'Semantic acknowledgement/setup chronology changed'
    observation = context['observation']
    assert all(observation['bindingBefore'][key] == value for key, value in native.items()), 'Original semantic profile differs from the retained engine'
    raw = observation['nativeSnapshots']['controllerBefore']
    return canonical_profile_projection(raw['profileDirectory']['witness'], raw['profileUrl'])


def require_ime_save_disposition(record, restoration):
    assert record['restoration'] == restoration
    origin, facts = require_tsf_pipeline(record)
    if origin == 'empty':
        from ime_engine_retirement import require_ime_retirement_admission
        require_ime_retirement_admission(record['imeEngineRetirement'], expected_native=record['imeKeyboardSession']['expectedNative'],
            expected_run=record['readiness']['source'], expected_case=record['case'], expected_source=record['readiness']['source']['sourceCommit'],
            expected_original_profile=original_ime_profile(record))
        _require_precommand_retirement_join(record)
    return facts


def validate_ime_evidence(record):
    architecture = native_arch.require_architecture(record.get('architecture', 'x64'))
    for field in ('nativeArchitecture', 'targetArchitecture'):
        if architecture == 'arm64' or field in record:
            native_arch.validate_native_architecture(record.get(field), architecture)
    require_ascii_prefix(record)
    profile = require_readiness(record.get('readiness', {}), architecture=record.get('architecture', 'x64'))['profile']
    active = record.get('activeProfile', {})
    assert active.get('activeLanguage') == 0x0412 and active.get('activeClsid', '').lower() == profile['providerClsid'].lower() and active.get('activeProfile', '').lower() == profile['profileGuid'].lower(), 'Captured active TSF profile differs from the signed Microsoft readiness profile'
    assert record.get('inputMethod') == 'SendInput-scancode' and record.get('unicodeInputUsed') is False, 'Unicode input is not an IME test'
    assert record.get('keyTokens') == EXPECTED_KEYS, 'Actual Dubeolsik and Backspace keys are required'
    assert record.get('activeLayout', 0) & 0xffff == 0x0412, 'Focused thread has no active Korean layout'
    events = record.get('events')
    assert isinstance(events, list) and 1 <= len(events) <= 512, 'Actual composition messages are missing'
    compositions, results = [], []
    for event in events:
        assert (event.get('pid'), event.get('tid'), event.get('hwnd')) == (record['officePid'], record['editorTid'], record['keyboardFocusHwnd']), 'Composition came from another process, thread or HWND'
        assert event.get('layout', 0) & 0xffff == 0x0412, 'Composition came from a different input language'
        if event.get('message') != 0x10f: continue
        composition, result = event.get('composition', ''), event.get('result', '')
        assert isinstance(composition, str) and isinstance(result, str) and len(composition) <= 255 and len(result) <= 255, 'Invalid composition receipt'
        if composition and (not compositions or composition != compositions[-1]): compositions.append(composition)
        if result and (not results or result != results[-1]): results.append(result)
    pending = iter(compositions)
    assert all(any(value == expected for value in pending) for expected in ('ㅎ', '하', '한', 'ㄱ', '그', '글', '그', '글')), 'Live Dubeolsik/Backspace composition transitions are missing'
    assert ''.join(results) == '한글', 'The IME did not commit the exact Korean result'
    expected = marker(record['module'])
    assert record.get('asciiPrefix') == ' ' + expected.split('한글')[0] and record.get('prefixInputLayout', 0) & 0xffff == 0x0409, 'ASCII setup was not captured before Korean activation on the original English layout'
    assert expected in record.get('savedText', ''), 'Saved XML has no distinct newly typed Korean marker'
    observed = record.get('reopened', {})
    verify_content(record['module'], observed)
    assert expected in observed.get('text', ''), 'Actual UNO reopen lost the Korean marker'
    assert record.get('layoutRestored') is True, 'Original owned profile/HKL was not restored'
    validate_restoration(record.get('restoration'))
    origin, facts = require_tsf_pipeline(record)
    if origin == 'empty':
        from ime_engine_retirement import require_ime_engine_retirement
        _require_precommand_retirement_join(record)
        require_ime_engine_retirement(record['imeEngineRetirement'], expected_native=record['imeKeyboardSession']['expectedNative'],
            expected_run=record['readiness']['source'], expected_case=record['case'], expected_source=record['readiness']['source']['sourceCommit'],
            expected_original_profile=original_ime_profile(record))
        assert record['imeCommands'][3]['startedAt'] <= record['imeEngineRetirement']['proofPhase']['closeReturnedAt'], 'Engine retirement predates the original restoration command'
    assert record['prefixInputLayout'] == record['restoration']['previousLayout'], 'ASCII setup and original input-state capture used different layouts'
    return {'imeVerified': True, 'backspaceCompositionVerified': True, **facts,
            'savedKoreanVerified': True, 'reopenedKoreanVerified': True}


# Fixed-width layout shared by native x64/ARM64 Python and observer DLL. WCHAR is uint16,
# even when these policy helpers are imported on a non-Windows test host.
class NativeEvent(ctypes.Structure):
    _fields_ = [('sequence', ctypes.c_uint32), ('message', ctypes.c_uint32),
                ('flags', ctypes.c_uint32), ('pid', ctypes.c_uint32), ('tid', ctypes.c_uint32),
                ('hwnd', ctypes.c_uint64), ('layout', ctypes.c_uint64),
                ('compositionBytes', ctypes.c_int32), ('resultBytes', ctypes.c_int32),
                ('origin', ctypes.c_uint32), ('composition', ctypes.c_uint16 * 256),
                ('result', ctypes.c_uint16 * 256)]


class NativeState(ctypes.Structure):
    _fields_ = [('magic', ctypes.c_uint32), ('version', ctypes.c_uint32),
                ('pid', ctypes.c_uint32), ('tid', ctypes.c_uint32),
                ('count', ctypes.c_int32), ('overflow', ctypes.c_int32),
                ('command', ctypes.c_uint32), ('ack', ctypes.c_uint32),
                ('previousLayout', ctypes.c_uint64), ('previousOpen', ctypes.c_uint32),
                ('previousConversion', ctypes.c_uint32), ('previousSentence', ctypes.c_uint32),
                ('status', ctypes.c_int32), ('activeLanguage', ctypes.c_uint32),
                ('activeClsid', ctypes.c_uint16 * 40), ('activeProfile', ctypes.c_uint16 * 40),
                ('previousProfileType', ctypes.c_uint32), ('previousLanguage', ctypes.c_uint32),
                ('previousClsid', ctypes.c_uint16 * 40), ('previousProfile', ctypes.c_uint16 * 40),
                ('previousProfileLayout', ctypes.c_uint64), ('activeProfileType', ctypes.c_uint32),
                ('activeProfileLayout', ctypes.c_uint64), ('profileManagerHresult', ctypes.c_int32),
                ('previousProfileHresult', ctypes.c_int32), ('activateProfileHresult', ctypes.c_int32),
                ('activeProfileHresult', ctypes.c_int32), ('activateLayoutError', ctypes.c_uint32),
                ('events', NativeEvent * 512),
                ('commandBudgets', native_mode.NativeCommandBudget * 4),
                ('targetHwnd', ctypes.c_uint64), ('rootHwnd', ctypes.c_uint64),
                ('previousTsfOpen', ctypes.c_int32), ('previousTsfConversion', ctypes.c_int32),
                ('tsfCaptured', ctypes.c_uint32), ('profileChangeAttempted', ctypes.c_uint32),
                ('immContextPresent', ctypes.c_uint32), ('immConversionSucceeded', ctypes.c_uint32),
                ('immOpen', ctypes.c_uint32), ('immConversion', ctypes.c_uint32), ('immSentence', ctypes.c_uint32),
                ('threadMode', native_mode.NativeModeReceipt),
                ('commandRejection', native_mode.NativeCommandRejection), ('nativeAttemptedMask', ctypes.c_uint32)]


OBSERVER_SOURCE = r'''
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <imm.h>
#include <msctf.h>
#include <stdint.h>
#include "ime_thread_mode_windows.h"
#include "ime_typed_origin.h"
#include "ime_command_admission.h"
struct Event { uint32_t sequence,message,flags,pid,tid; uint64_t hwnd,layout;
    int32_t compositionBytes,resultBytes; uint32_t origin; WCHAR composition[256],result[256]; };
struct State { uint32_t magic,version,pid,tid; volatile LONG count,overflow;
    uint32_t command,ack; uint64_t previousLayout; uint32_t previousOpen,previousConversion,previousSentence;
    int32_t status; uint32_t activeLanguage; WCHAR activeClsid[40],activeProfile[40];
    uint32_t previousProfileType,previousLanguage; WCHAR previousClsid[40],previousProfile[40];
    uint64_t previousProfileLayout; uint32_t activeProfileType; uint64_t activeProfileLayout;
    int32_t profileManagerHresult,previousProfileHresult,activateProfileHresult,activeProfileHresult;
    uint32_t activateLayoutError; Event events[512];
    opengeul_ime::CommandBudget commandBudgets[4]; uint64_t targetHwnd,rootHwnd;
    int32_t previousTsfOpen,previousTsfConversion; uint32_t tsfCaptured,profileChangeAttempted;
    uint32_t immContextPresent,immConversionSucceeded,immOpen,immConversion,immSentence;
    opengeul_ime::ModeReceipt threadMode; opengeul_ime::CommandRejection commandRejection; uint32_t nativeAttemptedMask; };
static State* shared = nullptr;
static HANDLE mapping = nullptr;
static TF_INPUTPROCESSORPROFILE oldProfile = {};
static bool haveOldProfile = false;
static bool initialized = false;
static opengeul_ime::TypedPair originalTsf = {};
static opengeul_ime::CommandAdmission commandAdmission = {};
static bool connect() {
    if (!shared) {
        mapping=OpenFileMappingW(FILE_MAP_ALL_ACCESS,FALSE,L"__MAPPING__");
        if (!mapping) return false;
        shared=(State*)MapViewOfFile(mapping,FILE_MAP_ALL_ACCESS,0,0,sizeof(State));
    }
    return shared && shared->magic==0x4f47494d && shared->version==4
        && shared->pid==GetCurrentProcessId() && shared->tid==GetCurrentThreadId();
}
static ITfInputProcessorProfileMgr* profiles() {
    CLSID clsid; IID iid;
    CLSIDFromString(L"{33C53A50-F456-4884-B049-85FD643ECFED}",&clsid);
    CLSIDFromString(L"{71C6E74C-0F28-11D8-A82A-00065B84435C}",&iid);
    ITfInputProcessorProfileMgr* mgr=nullptr;
    shared->profileManagerHresult=CoCreateInstance(clsid,nullptr,CLSCTX_INPROC_SERVER,iid,(void**)&mgr);
    return mgr;
}
static bool budget(const opengeul_ime::CommandBudget& limits) {
    LARGE_INTEGER now={},frequency={};
    return limits.counter>0 && QueryPerformanceFrequency(&frequency)
        && uint64_t(frequency.QuadPart)==limits.frequency && QueryPerformanceCounter(&now)
        && now.QuadPart>0 && uint64_t(now.QuadPart)<limits.counter;
}
static void failure(int32_t status) { if (!shared->status) shared->status=status; }
static bool original_target(HWND hwnd,bool input) {
    DWORD pid=0; const auto tid=GetWindowThreadProcessId(hwnd,&pid);
    return IsWindow(hwnd) && uint64_t(UINT_PTR(hwnd))==shared->targetHwnd
        && pid==shared->pid && tid==shared->tid && tid==GetCurrentThreadId()
        && (!input || (GetFocus()==hwnd && uint64_t(UINT_PTR(GetAncestor(GetForegroundWindow(),GA_ROOT)))==shared->rootHwnd));
}
static bool same_profile(const TF_INPUTPROCESSORPROFILE& a,const TF_INPUTPROCESSORPROFILE& b) {
    return a.dwProfileType==b.dwProfileType && a.langid==b.langid && a.hkl==b.hkl
        && IsEqualGUID(a.clsid,b.clsid) && IsEqualGUID(a.guidProfile,b.guidProfile);
}
static bool korean_profile(ITfInputProcessorProfileMgr* mgr, const GUID& category) {
    TF_INPUTPROCESSORPROFILE value={}; GUID clsid,profile;
    CLSIDFromString(L"__CLSID__",&clsid); CLSIDFromString(L"__PROFILE__",&profile);
    return mgr && mgr->GetActiveProfile(category,&value)==S_OK
        && value.dwProfileType==TF_PROFILETYPE_INPUTPROCESSOR && value.langid==0x0412
        && IsEqualGUID(value.clsid,clsid) && IsEqualGUID(value.guidProfile,profile)
        && (UINT_PTR(GetKeyboardLayout(0))&0xffff)==0x0412;
}
static bool observe_imm(HWND hwnd) {
    shared->immContextPresent=shared->immConversionSucceeded=0;
    shared->immOpen=shared->immConversion=shared->immSentence=0;
    HIMC context=ImmGetContext(hwnd);
    if (!context) return false;
    shared->immContextPresent=1; shared->immOpen=ImmGetOpenStatus(context);
    DWORD conversion=0,sentence=0;
    shared->immConversionSucceeded=ImmGetConversionStatus(context,&conversion,&sentence);
    shared->immConversion=conversion;shared->immSentence=sentence;
    ImmReleaseContext(hwnd,context);
    return shared->immConversionSucceeded!=0;
}
static void command(HWND hwnd, UINT sequence) {
    const auto publishedSequence=InterlockedCompareExchange((volatile LONG*)&shared->command,0,0);
    if (sequence<1 || sequence>4 || sequence!=UINT(publishedSequence) || shared->ack==sequence) return;
    MemoryBarrier();
    const auto published=shared->commandBudgets[sequence-1];
    opengeul_ime::CommandLease lease(commandAdmission,shared->commandRejection,sequence,published);
    shared->nativeAttemptedMask=commandAdmission.attemptedMask;
    if (!lease.Entered()) return; // Never overwrite active status/receipt/ACK on rejection.
    const auto limits=lease.budget;
    shared->status=0; shared->threadMode=opengeul_ime::ModeReceipt{};
    ITfInputProcessorProfileMgr* mgr=profiles();
    GUID category; CLSIDFromString(L"{34745C63-B2F0-4784-8B67-5E12C8701A31}",&category);
    if (!original_target(hwnd,sequence!=4)) failure(-43);
    if (!budget(limits)) failure(-20);
    if (sequence==1 && !shared->status) {
        shared->previousLayout=uint64_t(UINT_PTR(GetKeyboardLayout(0)));
        shared->previousProfileHresult=mgr ? mgr->GetActiveProfile(category,&oldProfile) : E_UNEXPECTED;
        haveOldProfile=(shared->previousProfileHresult==S_OK);
        if (haveOldProfile) {
            shared->previousProfileType=oldProfile.dwProfileType;shared->previousLanguage=oldProfile.langid;
            shared->previousProfileLayout=uint64_t(UINT_PTR(oldProfile.hkl));
            StringFromGUID2(oldProfile.clsid,shared->previousClsid,40);
            StringFromGUID2(oldProfile.guidProfile,shared->previousProfile,40);
        } else failure(-8);
        if (!observe_imm(hwnd)) failure(-3);
        shared->previousOpen=shared->immOpen;shared->previousConversion=shared->immConversion;
        shared->previousSentence=shared->immSentence;
        if (!shared->status) {
            opengeul_ime::WindowsThreadMode api(shared->threadMode,limits.counter,limits.frequency);
            const auto allowEmpty=haveOldProfile && opengeul_ime::EmptyOriginUsProfile(shared->previousLayout,
                oldProfile.dwProfileType,oldProfile.langid,uint64_t(UINT_PTR(oldProfile.hkl)),
                IsEqualGUID(oldProfile.clsid,GUID_NULL),IsEqualGUID(oldProfile.guidProfile,GUID_NULL));
            opengeul_ime::CaptureOriginalTypedMode(api,shared->threadMode,originalTsf,allowEmpty);
            if (shared->threadMode.status) failure(shared->threadMode.status);
            else {
                if (opengeul_ime::PairConcrete(originalTsf)) {
                    shared->previousTsfOpen=originalTsf.open.value;
                    shared->previousTsfConversion=originalTsf.conversion.value;
                } // EMPTY has no original numeric state; legacy scalar slots stay unused.
                shared->tsfCaptured=1; initialized=true;
            }
        }
        if (!budget(limits)) failure(-20);
        if (!shared->status) {
            shared->profileChangeAttempted=1;
            SetLastError(0); HKL korean=LoadKeyboardLayoutW(L"00000412",0);
            if (!korean || (UINT_PTR(korean)&0xffff)!=0x0412) {shared->activateLayoutError=GetLastError();failure(-1);}
            else if (!budget(limits)) failure(-20);
            else if (!ActivateKeyboardLayout(korean,0)) {shared->activateLayoutError=GetLastError();failure(-1);}
            if (!budget(limits)) failure(-20);
            if (!shared->status) {
                GUID clsid,profile; CLSIDFromString(L"__CLSID__",&clsid);CLSIDFromString(L"__PROFILE__",&profile);
                shared->activateProfileHresult=mgr->ActivateProfile(TF_PROFILETYPE_INPUTPROCESSOR,0x0412,clsid,profile,nullptr,0);
                if (shared->activateProfileHresult!=S_OK) failure(-2);
            }
        }
    } else if ((sequence==2 || sequence==3) && !shared->status) {
        if (!initialized || !shared->tsfCaptured) failure(-39);
        else if (!observe_imm(hwnd)) failure(-3); // Existing HIMC context gate remains fatal.
        else if (!korean_profile(mgr,category)) failure(-40);
        if (!shared->status) {
            opengeul_ime::WindowsThreadMode api(shared->threadMode,limits.counter,limits.frequency);
            if (sequence==2 && opengeul_ime::PairEmpty(originalTsf))
                opengeul_ime::SetEmptyOriginAsciiMode(api,shared->threadMode,originalTsf);
            else opengeul_ime::SetThreadMode(api,shared->threadMode,sequence,shared->previousTsfOpen,shared->previousTsfConversion);
            if (shared->threadMode.status) failure(shared->threadMode.status);
            if (!observe_imm(hwnd)) failure(-3);
            else if (!shared->immOpen || bool(shared->immConversion&IME_CMODE_NATIVE)!=(sequence==3)) failure(-41);
        }
    } else if (sequence==4 && !shared->status) {
        if (!initialized || !haveOldProfile || !shared->tsfCaptured || !shared->profileChangeAttempted) failure(-42);
        if (!shared->status) {
            SetLastError(0);
            if (!ActivateKeyboardLayout(HKL(UINT_PTR(shared->previousLayout)),0)) {shared->activateLayoutError=GetLastError();failure(-7);}
            if (!budget(limits)) failure(-20);
            if (!shared->status) {
                shared->activateProfileHresult=mgr ? mgr->ActivateProfile(oldProfile.dwProfileType,oldProfile.langid,
                    oldProfile.clsid,oldProfile.guidProfile,
                    oldProfile.dwProfileType==TF_PROFILETYPE_INPUTPROCESSOR ? nullptr : oldProfile.hkl,0) : E_UNEXPECTED;
                if (shared->activateProfileHresult!=S_OK) failure(-6);
            }
            TF_INPUTPROCESSORPROFILE restored={};
            if (!mgr || mgr->GetActiveProfile(category,&restored)!=S_OK || !same_profile(restored,oldProfile)) failure(-40);
            if (!shared->status) {
                opengeul_ime::WindowsThreadMode api(shared->threadMode,limits.counter,limits.frequency);
                if (opengeul_ime::PairEmpty(originalTsf))
                    opengeul_ime::CaptureEmptyOriginReturn(api,shared->threadMode,originalTsf);
                else opengeul_ime::SetThreadMode(api,shared->threadMode,4,shared->previousTsfOpen,shared->previousTsfConversion);
                if (shared->threadMode.status) failure(shared->threadMode.status);
                if (!observe_imm(hwnd)) failure(-3);
                else if (shared->immOpen!=shared->previousOpen || shared->immConversion!=shared->previousConversion
                         || shared->immSentence!=shared->previousSentence) failure(-41);
            }
        }
    } else if (sequence<1 || sequence>4) failure(-44);
    TF_INPUTPROCESSORPROFILE current={};
    shared->activeLanguage=0;shared->activeProfileType=0;shared->activeProfileLayout=0;
    shared->activeClsid[0]=0;shared->activeProfile[0]=0;
    shared->activeProfileHresult=mgr ? mgr->GetActiveProfile(category,&current) : E_UNEXPECTED;
    if (mgr) {
        if (shared->activeProfileHresult==S_OK) {
            shared->activeLanguage=current.langid;shared->activeProfileType=current.dwProfileType;
            shared->activeProfileLayout=uint64_t(UINT_PTR(current.hkl));
            StringFromGUID2(current.clsid,shared->activeClsid,40);StringFromGUID2(current.guidProfile,shared->activeProfile,40);
        }
        mgr->Release();
    }
    if (!budget(limits)) failure(-20);
    // Per-command TSF references and the in-thread command lease are closed before ACK.
    lease.Finish();
    MemoryBarrier(); InterlockedExchange((volatile LONG*)&shared->ack,sequence);
}
static void observe(HWND hwnd,UINT message,WPARAM wp,LPARAM lp,UINT origin) {
    if (!connect()) return;
    if (message==0x8351) { command(hwnd,(UINT)wp); return; }
    if (message!=WM_IME_STARTCOMPOSITION && message!=WM_IME_ENDCOMPOSITION && message!=WM_IME_COMPOSITION) return;
    DWORD pid=0; if(GetWindowThreadProcessId(hwnd,&pid)!=shared->tid || pid!=shared->pid) return;
    LONG index=InterlockedIncrement(&shared->count)-1;
    if(index<0 || index>=512) { InterlockedExchange(&shared->overflow,1); return; }
    Event* event=&shared->events[index];
    event->message=message; event->flags=(uint32_t)lp; event->pid=pid; event->tid=GetCurrentThreadId();
    event->hwnd=(uint64_t)(UINT_PTR)hwnd; event->layout=(uint64_t)(UINT_PTR)GetKeyboardLayout(0); event->origin=origin;
    if (message==WM_IME_COMPOSITION) {
        HIMC himc=ImmGetContext(hwnd);
        if (himc) {
            // Read IMM data only on the owning editor thread, never cross-process.
            if (lp&GCS_COMPSTR) {
                LONG bytes=ImmGetCompositionStringW(himc,GCS_COMPSTR,nullptr,0);
                event->compositionBytes=bytes;
                if(bytes>=0 && bytes<512 && !(bytes&1)) ImmGetCompositionStringW(himc,GCS_COMPSTR,event->composition,bytes);
            }
            if (lp&GCS_RESULTSTR) {
                LONG bytes=ImmGetCompositionStringW(himc,GCS_RESULTSTR,nullptr,0);
                event->resultBytes=bytes;
                if(bytes>=0 && bytes<512 && !(bytes&1)) ImmGetCompositionStringW(himc,GCS_RESULTSTR,event->result,bytes);
            }
            ImmReleaseContext(hwnd,himc);
        } else { event->compositionBytes=-99; event->resultBytes=-99; }
    }
    MemoryBarrier(); InterlockedExchange((volatile LONG*)&event->sequence,index+1);
}
extern "C" __declspec(dllexport) LRESULT CALLBACK HookCall(int code,WPARAM wp,LPARAM lp) {
    if(code>=0) { CWPSTRUCT* m=(CWPSTRUCT*)lp; observe(m->hwnd,m->message,m->wParam,m->lParam,1); }
    return CallNextHookEx(nullptr,code,wp,lp);
}
extern "C" __declspec(dllexport) LRESULT CALLBACK HookGet(int code,WPARAM wp,LPARAM lp) {
    if(code>=0 && wp==PM_REMOVE) { MSG* m=(MSG*)lp; observe(m->hwnd,m->message,m->wParam,m->lParam,2); }
    return CallNextHookEx(nullptr,code,wp,lp);
}
extern "C" __declspec(dllexport) unsigned int StateSize() { return sizeof(State); }
extern "C" __declspec(dllexport) unsigned int PublishCommand(State* target,UINT sequence,uint64_t counter,uint64_t frequency) {
    // This export runs in the controller's DLL copy. Do not connect to the hook
    // target, apply its PID/TID guard, or retain this transient mapping pointer.
    if (!target || target->magic!=0x4f47494d || target->version!=4) return 0;
    if (!opengeul_ime::InstallCommandBudget(target->commandBudgets,sequence,{counter,frequency})) return 0;
    MemoryBarrier(); InterlockedExchange((volatile LONG*)&target->command,sequence); return 1;
}
extern "C" __declspec(dllexport) unsigned int ReadSnapshot(State* source,State* destination,UINT* ackBefore,UINT* ackAfter) {
    // Controller-side acquire of the hook's published ACK precedes the copy.
    // These mapping/output pointers are transient and must never be retained.
    if (!source || !destination || source==destination || !ackBefore || !ackAfter
        || source->magic!=0x4f47494d || source->version!=4) return 0;
    *ackBefore=(UINT)InterlockedCompareExchange((volatile LONG*)&source->ack,0,0);
    MemoryBarrier(); CopyMemory(destination,source,sizeof(State)); MemoryBarrier();
    *ackAfter=(UINT)InterlockedCompareExchange((volatile LONG*)&source->ack,0,0);
    return (*ackBefore==*ackAfter && destination->ack==*ackBefore) ? 1 : 2;
}
BOOL WINAPI DllMain(HINSTANCE,DWORD,LPVOID) { return TRUE; }
'''


def utf16(array):
    return bytes(array).decode('utf-16-le').split('\0', 1)[0]


def remaining_setup(deadline, old_limit, *, clock=None):
    if deadline is None:
        return old_limit
    assert type(deadline) in (int, float) and math.isfinite(deadline), 'Invalid shared IME setup deadline'
    remaining = deadline - (time.monotonic() if clock is None else clock())
    assert remaining > 0, 'Shared IME setup deadline expired'
    return min(old_limit, remaining)


def discover_msvc(folder, vswhere, *, architecture='x64', setup_deadline=None, clock=time.monotonic):
    native_arch.require_architecture(architecture)
    component = ('Microsoft.VisualStudio.Component.VC.Tools.ARM64' if architecture == 'arm64'
                 else 'Microsoft.VisualStudio.Component.VC.Tools.x86.x64')
    command = [str(vswhere), '-latest', '-products', '*', '-requires',
        component, '-property', 'installationPath']
    started = clock()
    timeout = remaining_setup(setup_deadline, 60, clock=clock)

    def preserve(result, outcome):
        def encoded(value):
            return value.encode('utf-8') if isinstance(value, str) else value or b''
        (folder / 'compiler-discovery.log').write_bytes(encoded(getattr(result, 'stdout', None)) + encoded(getattr(result, 'stderr', None)))
        (folder / 'compiler-discovery.json').write_text(json.dumps({
            'stage': 'discover-msvc', 'command': command, 'timeoutSeconds': timeout,
            'setupDeadline': setup_deadline,
            'elapsedSeconds': clock() - started, 'outcome': outcome,
            'returncode': getattr(result, 'returncode', None),
            'exceptionType': type(result).__name__ if isinstance(result, Exception) else None,
            'exceptionMessage': str(result) if isinstance(result, Exception) else None,
            'winerror': getattr(result, 'winerror', None)}, indent=2), encoding='utf-8')

    try:
        # A hosted VS installation query exceeded 10s before compilation.
        # Allow the same one-shot bound as cl.exe, retaining the original output.
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    except (subprocess.TimeoutExpired, OSError) as exc:
        preserve(exc, 'timeout' if isinstance(exc, subprocess.TimeoutExpired) else 'launch-error')
        raise
    preserve(result, 'complete' if result.returncode == 0 else 'nonzero-exit')
    result.check_returncode()
    remaining_setup(setup_deadline, 60, clock=clock)
    return result.stdout.strip()


def compile_observer(folder, mapping, profile, *, architecture='x64', setup_deadline=None, clock=time.monotonic):
    native_arch.require_architecture(architecture)
    remaining_setup(setup_deadline, 60, clock=clock)
    source, library = folder / 'ime-observer.cpp', folder / 'ime-observer.dll'
    for name in ('ime_thread_mode.h', 'ime_thread_mode_windows.h', 'ime_command_admission.h', 'ime_typed_origin.h'):
        (folder / name).write_bytes(Path(__file__).with_name(name).read_bytes())
    source.write_text(OBSERVER_SOURCE.replace('__MAPPING__', mapping.replace('\\', '\\\\'))
        .replace('__CLSID__', profile['providerClsid']).replace('__PROFILE__', profile['profileGuid']), encoding='utf-8')
    compiler = shutil.which('cl.exe')
    command = ['cl.exe', '/nologo', '/LD', '/O2', '/MT', '/EHsc', '/utf-8', str(source),
               '/link', '/MACHINE:' + ('ARM64' if architecture == 'arm64' else 'X64'), '/OUT:' + str(library), 'user32.lib', 'imm32.lib', 'ole32.lib', 'oleaut32.lib', 'uuid.lib']
    if compiler and architecture == 'x64':
        result = subprocess.run(command, cwd=folder, capture_output=True,
            timeout=remaining_setup(setup_deadline, 60, clock=clock))
    else:
        vswhere = Path(os.environ.get('ProgramFiles(x86)', r'C:\Program Files (x86)')) / 'Microsoft Visual Studio/Installer/vswhere.exe'
        found = discover_msvc(folder, vswhere, architecture=architecture,
            setup_deadline=setup_deadline, clock=clock)
        vcvars = Path(found) / ('VC/Auxiliary/Build/vcvarsall.bat' if architecture == 'arm64'
                                else 'VC/Auxiliary/Build/vcvars64.bat')
        assert vcvars.is_file(), 'Microsoft native ' + architecture + ' C++ build tools are required for the in-process observer'
        script = folder / 'compile-observer.cmd'
        script.write_text('@echo off\ncall "' + str(vcvars) + '"' + (' arm64' if architecture == 'arm64' else '') + '\nif errorlevel 1 exit /b 1\n' + subprocess.list2cmdline(command) + '\n', encoding='utf-8')
        result = subprocess.run(['cmd.exe', '/d', '/c', str(script)], cwd=folder,
            capture_output=True, timeout=remaining_setup(setup_deadline, 60, clock=clock))
    (folder / 'compiler.log').write_bytes(result.stdout + result.stderr)
    assert result.returncode == 0 and library.is_file(), 'The native IME observer did not compile; inspect compiler.log'
    remaining_setup(setup_deadline, 60, clock=clock)
    return native_arch.require_native_pe(library, architecture)


class CompositionObserver:
    def __init__(self, api, root, child, focus, pid, folder, profile, *, architecture='x64', setup_deadline=None):
        remaining_setup(setup_deadline, 60)
        self.native_architecture = native_arch.validate_native_architecture(
            native_arch.observe_native_architecture(), architecture)
        self.target_architecture = native_arch.observe_owned_process(pid, architecture)
        self.api, self.root, self.child, self.focus, self.pid = api, root, child, focus, pid
        self.expected_profile = dict(profile)
        self.tid = int(api.user.GetWindowThreadProcessId(focus, None))
        assert self.tid and api.pid(focus) == pid, 'Observer target is not the owned editor input thread'
        self.mapping_name = 'Local\\OpenGeulIme_' + uuid.uuid4().hex
        self.mapping = mmap.mmap(-1, ctypes.sizeof(NativeState), tagname=self.mapping_name)
        state = NativeState()
        state.magic, state.version, state.pid, state.tid = 0x4f47494d, 4, pid, self.tid
        state.targetHwnd, state.rootHwnd = focus, root
        self.mapping[:] = bytes(state)
        try:
            library = compile_observer(folder, self.mapping_name, profile,
                architecture=architecture, setup_deadline=setup_deadline)
        except BaseException:
            self.close()
            raise
        native_arch.require_native_pe(library, architecture)
        self.dll = ctypes.WinDLL(str(library), use_last_error=True)
        self.dll.StateSize.restype = ctypes.c_uint32
        assert self.dll.StateSize() == ctypes.sizeof(NativeState), 'Native observer memory layout differs from controller'
        self.dll.PublishCommand.argtypes = [ctypes.POINTER(NativeState), ctypes.c_uint32, ctypes.c_uint64, ctypes.c_uint64]
        self.dll.PublishCommand.restype = ctypes.c_uint32
        self.dll.ReadSnapshot.argtypes = [ctypes.POINTER(NativeState), ctypes.POINTER(NativeState),
            ctypes.POINTER(ctypes.c_uint32), ctypes.POINTER(ctypes.c_uint32)]
        self.dll.ReadSnapshot.restype = ctypes.c_uint32
        api.user.SetWindowsHookExW.argtypes = [ctypes.c_int, ctypes.c_void_p, W.HINSTANCE, W.DWORD]
        api.user.SetWindowsHookExW.restype = W.HANDLE
        api.user.UnhookWindowsHookEx.argtypes = [W.HANDLE]
        api.user.UnhookWindowsHookEx.restype = W.BOOL
        api.user.SendMessageTimeoutW.argtypes = [W.HWND, W.UINT, W.WPARAM, W.LPARAM, W.UINT, W.UINT, ctypes.POINTER(ctypes.c_size_t)]
        api.user.SendMessageTimeoutW.restype = W.LPARAM
        api.user.GetKeyboardLayout.argtypes = [W.DWORD]
        api.user.GetKeyboardLayout.restype = W.HANDLE
        self.hooks, self.commands, self.restored = [], [], False
        self.command_attempts = set()
        self.activation_attempted = False
        self.original_tsf = self.original_context = None
        try:
            for kind, name in ((4, 'HookCall'), (3, 'HookGet')):
                remaining_setup(setup_deadline, 60)
                address = ctypes.cast(getattr(self.dll, name), ctypes.c_void_p)
                handle = api.user.SetWindowsHookExW(kind, address, self.dll._handle, self.tid)
                if not handle: raise ctypes.WinError(ctypes.get_last_error())
                self.hooks.append(handle)
            remaining_setup(setup_deadline, 60)
        except Exception:
            self.close()
            raise

    def state(self):
        view = NativeState.from_buffer(self.mapping)
        snapshot, before, after = NativeState(), ctypes.c_uint32(), ctypes.c_uint32()
        try:
            copied = self.dll.ReadSnapshot(ctypes.byref(view), ctypes.byref(snapshot),
                ctypes.byref(before), ctypes.byref(after))
        finally:
            del view
        assert type(copied) is int and copied in (1, 2), 'Native IME ACK acquire/copy failed'
        snapshot.snapshotEvidence = dict(copyReturn=copied, ackBefore=int(before.value),
            ackAfter=int(after.value), stable=copied == 1 and before.value == after.value == snapshot.ack)
        return snapshot

    def require_target(self):
        assert self.api.require_editor_focus(self.root, self.child) == self.focus, 'IME input focus HWND changed'
        assert self.api.pid(self.focus) == self.pid and self.api.user.GetWindowThreadProcessId(self.focus, None) == self.tid, 'IME target process/thread identity changed'

    def require_restore_target(self):
        assert self.api.user.IsWindow(self.focus), 'Original restore HWND no longer exists'
        assert self.api.pid(self.focus) == self.pid and self.api.user.GetWindowThreadProcessId(self.focus, None) == self.tid, 'Original restore process/thread changed'
        assert self.api.user.GetAncestor(self.focus, 2) == self.root and (self.focus == self.child or self.api.user.IsChild(self.child, self.focus)), 'Original restore HWND left its owned child'

    @property
    def restoration_required(self):
        return self.activation_attempted and 4 not in self.command_attempts and self.state().profileChangeAttempted == 1

    def _command_snapshot(self, state, command):
        limits = state.commandBudgets[command - 1]
        return {'command': command, 'status': int(state.status), 'nativeAck': int(state.ack),
            'policyVersion': int(state.version),
            'nativeContext': {key: int(getattr(state, key)) for key in ('magic', 'version', 'pid', 'tid', 'targetHwnd', 'rootHwnd')},
            'snapshotEvidence': dict(state.snapshotEvidence),
            'publishedCommand': int(state.command), 'nativeAttemptedMask': int(state.nativeAttemptedMask),
            'commandRejection': {name: int(getattr(state.commandRejection, name))
                for name, _ in native_mode.NativeCommandRejection._fields_},
            'layout': int(self.api.user.GetKeyboardLayout(self.tid) or 0),
            'activeLanguage': state.activeLanguage, 'activeClsid': utf16(state.activeClsid),
            'activeProfile': utf16(state.activeProfile), 'previousLayout': state.previousLayout,
            'previousProfileType': state.previousProfileType, 'previousLanguage': state.previousLanguage,
            'previousClsid': utf16(state.previousClsid), 'previousProfile': utf16(state.previousProfile),
            'previousProfileLayout': state.previousProfileLayout, 'activeProfileType': state.activeProfileType,
            'activeProfileLayout': state.activeProfileLayout, 'profileManagerHresult': state.profileManagerHresult,
            'previousProfileHresult': state.previousProfileHresult, 'activateProfileHresult': state.activateProfileHresult,
            'activeProfileHresult': state.activeProfileHresult, 'activateLayoutError': state.activateLayoutError,
            'observerClsid': native_mode.OBSERVER_CLSID, 'threadMode': native_mode.receipt_dict(state.threadMode),
            'tsfModeCaptured': int(state.tsfCaptured), 'profileChangeAttempted': int(state.profileChangeAttempted),
            'previousTsfOpen': int(state.previousTsfOpen), 'previousTsfConversion': int(state.previousTsfConversion),
            'modeDeadlineCounter': int(limits.counter), 'modeCounterFrequency': int(limits.frequency),
            'immState': dict(contextPresent=int(state.immContextPresent), conversionSucceeded=int(state.immConversionSucceeded),
                open=int(state.immOpen), conversion=int(state.immConversion), sentence=int(state.immSentence)),
            'previousImmState': dict(open=int(state.previousOpen), conversion=int(state.previousConversion), sentence=int(state.previousSentence))}

    def command(self, command, *, setup_deadline=None):
        assert type(command) is int and command in (1, 2, 3, 4)
        assert command not in self.command_attempts, 'Original native IME command cannot retry or renew its budget'
        self.command_attempts.add(command)
        row = dict(command=command, acknowledged=False, success=False, nativeCallAttempts=0, startedAt=time.monotonic())
        self.commands.append(row)  # Failure/rejection evidence survives a missing ACK.
        try:
            if command == 4: self.require_restore_target()
            else: self.require_target()
            bounded_deadline = time.monotonic() + remaining_setup(setup_deadline, 5)
            counter, frequency = native_mode.counter_budget(bounded_deadline, clock=time.monotonic)
            slot = native_mode.NativeCommandBudget(counter, frequency)
            offset = NativeState.commandBudgets.offset + (command - 1) * ctypes.sizeof(slot)
            assert not any(self.mapping[offset:offset + ctypes.sizeof(slot)]), 'Native IME command budget was already published'
            row.update(deadline=bounded_deadline, requestedBudget=dict(counter=counter, frequency=frequency))
            view = NativeState.from_buffer(self.mapping)
            try: published = self.dll.PublishCommand(ctypes.byref(view), command, counter, frequency)
            finally: del view
            row['nativePublicationReturn'] = published if type(published) is int else repr(published)
            assert type(published) is int and published == 1, 'Native IME command publication failed'
            if command == 1: self.activation_attempted = True
            result = ctypes.c_size_t()
            milliseconds = int(remaining_setup(bounded_deadline, 5) * 1000)
            assert milliseconds > 0, 'Shared IME setup has no native command budget'
            row['nativeCallAttempts'] = 1
            if not self.api.user.SendMessageTimeoutW(self.focus, 0x8351, command, 0, 2, milliseconds, ctypes.byref(result)):
                raise ctypes.WinError(ctypes.get_last_error())
            state = wait_for(lambda: (value if (value := self.state()).snapshotEvidence['stable']
                and value.ack == command and value.snapshotEvidence['ackBefore'] == command
                and value.snapshotEvidence['ackAfter'] == command else None),
                remaining_setup(bounded_deadline, 5))
            row.update(self._command_snapshot(state, command), acknowledged=True)
            assert state.status == 0, 'Owned native IME command failed: ' + str(row)
            assert not row['commandRejection']['count'], 'Conflicting native IME command was rejected; subsequent input is blocked'
            assert (row['modeDeadlineCounter'], row['modeCounterFrequency']) == (counter, frequency), 'Native IME command used a different published budget'
            assert state.tsfCaptured == 1, 'Original TSF mode state was not captured before profile activation'
            context = require_mode_context(row)
            assert context[2:] == (self.pid, self.tid, self.focus, self.root), 'Native mode snapshot changed the original target'
            if command == 1:
                assert self.original_tsf is None and self.original_context is None, 'Original typed memento cannot be replaced'
                observed = native_mode.require_typed_mode_receipt(row['threadMode'], 1, allow_empty=original_empty_us_profile(row))
            else:
                assert context == self.original_context, 'Typed original belongs to another native context'
                observed = native_mode.require_typed_mode_receipt(row['threadMode'], command, original=self.original_tsf)
            row['typedValues'] = native_mode.typed_pair_dict(observed)
            origin = observed if command == 1 else self.original_tsf
            row['tsfOrigin'] = 'empty' if origin[0][1] == 0 else 'i4'
            if command in (2, 3, 4):
                assert state.immContextPresent == state.immConversionSucceeded == 1, 'Original HIMC conversion getter failed'
                if command in (2, 3):
                    assert state.immOpen and bool(state.immConversion & 1) == (command == 3), 'HIMC mode does not acknowledge requested conversion'
                    assert (state.activeProfileHresult == 0 and state.activeLanguage == 0x0412
                        and utf16(state.activeClsid).lower() == self.expected_profile['providerClsid'].lower()
                        and utf16(state.activeProfile).lower() == self.expected_profile['profileGuid'].lower()), 'Mode acknowledgement changed the attested Korean TSF profile'
                else:
                    assert (state.immOpen, state.immConversion, state.immSentence) == (state.previousOpen, state.previousConversion, state.previousSentence), 'Exact original IMM state was not read back'
            remaining_setup(bounded_deadline, 5)
            if command == 1:
                self.original_tsf, self.original_context = observed, context
            if command == 4:
                assert int(self.api.user.GetKeyboardLayout(self.tid) or 0) == state.previousLayout, 'Original input layout was not restored'
                validate_restoration(row)
                row.update(profileHklRestored=True, immEqual=True,
                    typedStateEqual=observed == self.original_tsf,
                    restorationDisposition='empty-origin-retirement-required' if row['tsfOrigin'] == 'empty' else 'concrete-restored')
                remaining_setup(bounded_deadline, 5)
                self.restored = True
            row['success'] = True
            return row
        except BaseException as exc:
            row['error'] = type(exc).__name__ + ': ' + str(exc)
            try: row['nativeStateAtFailure'] = self._command_snapshot(self.state(), command)
            except BaseException as later: row['failureSnapshotError'] = type(later).__name__ + ': ' + str(later)
            raise

    def events(self):
        state = self.state()
        assert not state.overflow, 'Native composition receipt buffer overflowed'
        events = []
        for index in range(min(max(state.count, 0), 512)):
            row = state.events[index]
            if row.sequence != index + 1: break
            assert 0 <= row.compositionBytes < 512 and 0 <= row.resultBytes < 512, 'Native composition string was unavailable or too large'
            events.append({'sequence': row.sequence, 'message': row.message, 'flags': row.flags,
                'pid': row.pid, 'tid': row.tid, 'hwnd': row.hwnd, 'layout': row.layout,
                'origin': 'sent' if row.origin == 1 else 'posted',
                'composition': utf16(row.composition), 'result': utf16(row.result)})
        return events

    def pending(self, expected, after):
        events = self.events()[after:]
        return any(row['message'] == 0x10f and row['composition'] == expected for row in events)

    def close(self):
        errors = []
        for hook in reversed(getattr(self, 'hooks', [])):
            if not self.api.user.UnhookWindowsHookEx(hook): errors.append(str(ctypes.get_last_error()))
        self.hooks = []
        if getattr(self, 'mapping', None) is not None:
            self.mapping.close()
            self.mapping = None
        assert not errors, 'Owned editor observer hook cleanup failed: ' + ','.join(errors)


class KeyboardInput(ctypes.Structure):
    _fields_ = [('wVk', W.WORD), ('wScan', W.WORD), ('dwFlags', W.DWORD),
                ('time', W.DWORD), ('dwExtraInfo', ctypes.c_size_t)]


class MouseInput(ctypes.Structure):
    _fields_ = [('dx', W.LONG), ('dy', W.LONG), ('mouseData', W.DWORD), ('dwFlags', W.DWORD),
                ('time', W.DWORD), ('dwExtraInfo', ctypes.c_size_t)]


class InputPayload(ctypes.Union):
    _fields_ = [('keyboard', KeyboardInput), ('mouse', MouseInput)]


class Input(ctypes.Structure):
    _fields_ = [('type', W.DWORD), ('payload', InputPayload)]


def physical_key(observer, token, record):
    observer.require_target()
    assert int(observer.api.user.GetKeyboardLayout(observer.tid) or 0) & 0xffff == 0x0412, 'Korean layout changed before physical key'
    rows = scan_events([token])
    payload = (Input * len(rows))()
    for item, row in zip(payload, rows):
        item.type = 1
        item.payload.keyboard = KeyboardInput(row['vk'], row['scan'], row['flags'], 0, 0)
    user = observer.api.user
    user.SendInput.argtypes = [W.UINT, ctypes.POINTER(Input), ctypes.c_int]
    user.SendInput.restype = W.UINT
    assert user.SendInput(len(payload), payload, ctypes.sizeof(Input)) == len(payload), 'Physical scan-code input was not fully delivered'
    record['keyTokens'].append(token)
    record.setdefault('scanCodeInputs', []).extend(rows)


def reopen_one(suite, source, module):
    from engine_smoke import Engine, observe
    engine, document = Engine(suite), None
    try:
        engine.start()
        document = engine.load(source.as_uri())
        observed = observe(module, document)
        verify_content(module, observed)
        assert marker(module) in observed['text'], 'Actual Office reopen lost Korean input'
        return observed
    finally:
        engine.close_document(document)
        engine.cleanup()
        assert not engine.cleanup_errors, 'UNO reopen cleanup failed: ' + str(engine.cleanup_errors)


def retained_setup_shell(process, suite, keyboard, *, calc_navigation_initial=False):
    # This later, fuller Popen observation is joined to the keyboard's true
    # first admission; it is never presented as an earlier reader witness.
    from lifecycle_smoke import retained_writer_shell
    from writer_model_barrier import require_original_shell
    assert type(calc_navigation_initial) is bool, 'Unknown retained IME shell admission mode'
    require_target = keyboard.require_calc_navigation_initial_target if calc_navigation_initial else keyboard.require_target
    require_target()
    evidence = {}
    retained_writer_shell(process, suite, evidence)
    require_original_shell(evidence, keyboard.binding, suite)
    assert evidence['handleValue'] == keyboard.shell['handleValue'], 'Calc setup replaced the original Popen HANDLE'
    require_target()
    return evidence


def retain_ime_focus_failure_diagnostics(record, process, keyboard):
    """Append one separate native observation after the primary focus failure."""
    field = 'imeFocusFailureDiagnostics'
    if record.get('stage') != 'focus-editor' or record.get('success') is not False or field in record:
        return
    receipt = dict(schemaVersion=1, kind='ime-focus-failure-separate-native-observation',
        status='unavailable', triggerStage='focus-editor', actionOutcomeUnaffected=True,
        historicalScopeJoined=False,
        observationScope='failure-time separate observation after primary failure capture; no earlier HWND, process generation or input recipient is identified',
        bindingSource='original IMEKeyboardSession.binding and matching case record',
        foreignRootHintSource='unavailable')
    record[field] = receipt  # Reserve the attempt before any import or native call.
    try:
        assert isinstance(record.get('error'), str) and isinstance(record.get('traceback'), str), 'Primary failure was not retained'
        binding = keyboard.binding
        keys = ('shellPid', 'officePid', 'suiteHwnd', 'parentHwnd', 'childHwnd', 'rootHwnd',
                'shellCreationTime', 'officeCreationTime')
        original = {key: binding[key] for key in keys}
        for key, value in original.items():
            assert type(value) is int and 0 < value < 2**(32 if key in ('shellPid', 'officePid') else 64), 'Invalid original native diagnostic binding'
        assert original['rootHwnd'] == original['suiteHwnd'] and original['shellPid'] != original['officePid']
        assert original['officeCreationTime'] >= original['shellCreationTime']
        assert type(process.pid) is int and process.pid == original['shellPid']
        for key, source in (('shellPid', 'shellPid'), ('officePid', 'officePid'), ('suiteHwnd', 'windowHwnd'),
                            ('parentHwnd', 'parentHwnd'), ('childHwnd', 'childHwnd')):
            assert type(record[source]) is int and record[source] == original[key], 'Case native diagnostic binding changed'
        session = record['imeKeyboardSession']
        assert all(type(session['expectedNative'][key]) is int and session['expectedNative'][key] == value
                   for key, value in original.items()), 'Keyboard native diagnostic binding changed'
        tid = keyboard.tid
        tid = tid if type(tid) is int and 0 < tid < 2**32 else 0
        foreign = 0
        scope = session.get('lastGuardObservation', {}).get('scope', {})
        for edge in ('after', 'before'):
            candidate = scope.get(edge, {}).get('foreground', {}).get('rootHwnd')
            if type(candidate) is int and 0 < candidate < 2**64 and candidate != original['suiteHwnd']:
                foreign = candidate
                receipt['foreignRootHintSource'] = 'lastGuardObservation.scope.' + edge + '.foreground.rootHwnd'
                break
        receipt.update(originalBinding=original, ownedThreadId=tid, foreignRootHint=foreign)
        from activation_failure_diagnostics import collect_failure_diagnostics, MAX_BYTES
        observation = collect_failure_diagnostics(original['suiteHwnd'], original['shellPid'], tid, foreign)
        receipt.update(status='retained', observation=observation)
        assert len(json.dumps(receipt, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode()) <= MAX_BYTES, 'Separate failure diagnostic receipt exceeds existing byte bound'
    except BaseException as exc:
        receipt.pop('observation', None)
        try: message = str(exc)
        except BaseException: message = '<unprintable diagnostic exception>'
        receipt.update(status='unavailable', error=(type(exc).__name__ + ': ' + message)[:160].encode('utf-8', errors='replace').decode('utf-8'))


def case(suite, fixtures, output, readiness, module, extension, *, prepared_library):
    from pywinauto import Desktop
    from windows_smoke import click_owned_editor, prepare_editor_focus
    from ime_engine_retirement import admit_ime_retirement
    name = 'ime-' + module
    folder = output / name
    folder.mkdir()
    original = require_engine_fixture(fixtures, module, extension)
    original_bytes = original.read_bytes()
    source = folder / original.name
    shutil.copyfile(original, source)
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    process = launch_suite([str(suite / 'OpenGeul.Office.exe'), '--module', module, '--file', str(source)], suite, output, name)
    record = {'module': module, 'case': name, 'imePolicyVersion': 4, 'kind': 'native-korean-ime', 'shellPid': process.pid,
              'file': str(source), 'success': False, 'imeVerified': False, 'stage': 'attach',
              'inputMethod': 'SendInput-scancode', 'unicodeInputUsed': False, 'keyTokens': [],
              'readiness': readiness, 'architecture': {0x8664: 'x64', 0xaa64: 'arm64'}[readiness['nativeMachine']]}
    observer = keyboard = retirement = primary = None
    api = Windows()
    try:
        hwnd, parent, child, office_pid = verified_attachment(api, process, module)
        record.update(windowHwnd=hwnd, parentHwnd=parent, childHwnd=child, officePid=office_pid)
        window = Desktop(backend='win32').window(handle=hwnd).wrapper_object()
        window.maximize()
        activate_owned_suite(api, process, hwnd, record)
        setup_started = time.monotonic()
        setup_deadline = setup_started + 60
        record['imeSetupBudget'] = dict(startedAt=setup_started, deadline=setup_deadline,
            deadlineScope='focus-navigation-ascii-reader-cleanup-observer-and-native-mode-setup')
        wait_for(lambda: api.user.GetAncestor(api.user.GetForegroundWindow(), 2) == hwnd,
            remaining_setup(setup_deadline, 10))
        keyboard = IMEKeyboardSession(api, process, hwnd, parent, child, office_pid,
            module, record, setup_deadline)
        keyboard.start()
        record['stage'] = 'focus-editor'
        prepare_editor_focus(api, hwnd, child, process.pid, office_pid, record,
            lambda: click_owned_editor(api, process, hwnd, parent, child, office_pid, record),
            lambda: keyboard.focus_editor(record['editorFocusReadiness']['deadline']),
            seconds=remaining_setup(setup_deadline, 5))
        keyboard.editor_ready(record['editorFocusReadiness'])
        if module == 'calc':
            keyboard.navigate_calc(suite, source, original_bytes,
                original_shell=retained_setup_shell(process, suite, keyboard, calc_navigation_initial=True))
        else:
            keyboard.navigate()
        focus = keyboard.focus
        record.update(editorTid=keyboard.tid, keyboardFocusHwnd=focus)
        record['stage'] = 'verify-pre-prefix-editing-context'
        pre = observe_ime_semantic_setup(suite, source, original_bytes, record, setup_deadline,
            original_shell=retained_setup_shell(process, suite, keyboard),
            expected_native=dict(keyboard.binding),
            require_current=lambda: keyboard.require_context_target('imeSemanticContext'), phase='pre')
        keyboard.semantic_ready(pre, phase='pre')
        def send_prefix(prefix):
            keyboard.require_prefix_ready()
            return ascii_input.type_ascii(api, hwnd, child, prefix, record,
                pause=0.04, deadline=setup_deadline, original_popen=keyboard.process,
                native_binding=keyboard.binding, prepared_library=prepared_library)
        prepare_ascii_prefix(keyboard, module, record, send_prefix)
        record['stage'] = 'verify-post-prefix-editing-context'
        post = observe_ime_semantic_setup(suite, source, original_bytes, record, setup_deadline,
            original_shell=retained_setup_shell(process, suite, keyboard),
            expected_native=dict(keyboard.binding),
            require_current=lambda: keyboard.require_context_target('imeSemanticContext'), phase='post', expected_prefix=record['asciiPrefix'])
        keyboard.semantic_ready(post, phase='post')
        if module == 'calc':
            record['stage'] = 'verify-calc-context-before-ime-observer'
            observe_calc_setup(suite, source, original_bytes, record, setup_deadline,
                original_shell=retained_setup_shell(process, suite, keyboard),
                expected_native=dict(keyboard.binding),
                require_current=lambda: keyboard.require_context_target('calcSetupContext'))
        record['stage'] = 'install-owned-thread-observer'
        observer = CompositionObserver(api, hwnd, child, focus, office_pid, folder, readiness['profile'],
            architecture=record['architecture'], setup_deadline=setup_deadline)
        record.update(nativeArchitecture=observer.native_architecture, targetArchitecture=observer.target_architecture)
        assert observer.tid == keyboard.tid, 'Native observer differs from retained keyboard editor thread'
        keyboard.setup_complete()
        require_ascii_prefix(record)
        record['stage'] = 'activate-microsoft-korean-profile'
        # Origin is unknown until command1. Admit a separate read-only HANDLE
        # while the original keyboard HANDLE is still live, before any activation.
        retirement = admit_ime_retirement(keyboard=keyboard, original_shell=process, suite=suite,
            case_name=name, record=record, setup_deadline=setup_deadline,
            run_binding=readiness['source'], diagnostics_root=Path(os.environ['OPENGEUL_SUITE_DIAGNOSTICS']),
            original_profile=original_ime_profile(record))
        active = observer.command(1, setup_deadline=setup_deadline)
        wait_for(lambda: int(api.user.GetKeyboardLayout(observer.tid) or 0) & 0xffff == 0x0412,
            remaining_setup(setup_deadline, 10))
        profile = readiness['profile']
        assert active['activeLanguage'] == 0x0412 and active['activeClsid'].lower() == profile['providerClsid'].lower() and active['activeProfile'].lower() == profile['profileGuid'].lower(), 'Focused editor TSF profile differs from the attested Microsoft IME'
        record['activeLayout'] = int(api.user.GetKeyboardLayout(observer.tid) or 0)
        record['activeProfile'] = active
        observer.command(2, setup_deadline=setup_deadline)  # Existing context gate; actual composition proves editing.
        observer.command(3, setup_deadline=setup_deadline)
        remaining_setup(setup_deadline, 60)
        record['imeSetupBudget']['finishedAt'] = time.monotonic()
        assert record['imeSetupBudget']['finishedAt'] <= setup_deadline, 'Native IME setup exceeded its shared deadline'
        record['stage'] = 'physical-dubeolsik-composition'
        for token, expected in zip(EXPECTED_KEYS[:-1], ('ㅎ', '하', '한', 'ㄱ', '그', '글', '그', '글')):
            after = len(observer.events())
            physical_key(observer, token, record)
            wait_for(lambda: observer.pending(expected, after), 10)
        window.capture_as_image().save(output / (name + '-composing.png'))
        record['stage'] = 'commit-native-composition'
        physical_key(observer, 'RIGHT', record)
        wait_for(lambda: any(row['result'] == '글' for row in observer.events()), 10)
        record['events'] = observer.events()
        record['stage'] = 'restore-owned-input-thread'
        record['restoration'] = observer.command(4)
        record['layoutRestored'] = observer.restored
        record['imeCommands'] = observer.commands
        record.update({key: record['restoration'][key] for key in
            ('profileHklRestored', 'immEqual', 'typedStateEqual', 'restorationDisposition')})
        observer.close()
        observer = None
        save_started = time.monotonic()
        save_deadline = save_started + 30
        record['imeSaveBudget'] = dict(startedAt=save_started, deadline=save_deadline)
        keyboard.begin_save(record['restoration'], save_deadline)
        record['stage'] = 'save-ctrl-s'
        keyboard.save()
        keyboard.close()
        wait_for(lambda: marker(module) in package_text(source), remaining_setup(save_deadline, 30))
        wait_for(lambda: not api.title(hwnd).startswith('* '), remaining_setup(save_deadline, 10))
        record['savedText'] = package_text(source)
        window.capture_as_image().save(output / (name + '-saved.png'))
        assert not api.windows(office_pid), api.external_window_message(office_pid, 'IME opened an external Office document window')
        calc_proof = None
        if module == 'calc':
            from windows_smoke import _verified_saved_calc_close_proof
            from calc_model_barrier import baseline_from_ooxml
            calc_proof = _verified_saved_calc_close_proof(suite, folder, source,
                baseline_from_ooxml(original.read_bytes()), suffix=' ' + marker(module))
            close_document(api, process, hwnd, child, record, calc_close_proof=calc_proof)
        else:
            close_document(api, process, hwnd, child, record)
        close_home(api, process, record)
        if record['activeProfile']['tsfOrigin'] == 'empty':
            retirement.verify_after_close_home(close_returned_at=time.monotonic())
        retirement.close()  # Required proof/release precedes independent reopen.
        record['stage'] = 'actual-uno-reopen'
        result_path = folder / 'reopened.json'
        command = [str(suite / 'Office/program/python.exe'), str(Path(__file__).resolve()),
            '--suite', str(suite), '--verify-one', module, '--file', str(source), '--reopen-output', str(result_path)]
        reopened = subprocess.run(command, capture_output=True, timeout=120)
        (folder / 'reopen.log').write_bytes(reopened.stdout + reopened.stderr)
        assert reopened.returncode == 0, 'Actual Office Korean-content reopen failed; inspect reopen.log'
        record['reopened'] = json.loads(result_path.read_text(encoding='utf-8'))
        record.update(validate_ime_evidence(record))
        record.update(success=True, cleanClose=True, stage='complete', beforeSha256=before,
            afterSha256=hashlib.sha256(source.read_bytes()).hexdigest(),
            originalFixtureUnchanged=hashlib.sha256(original.read_bytes()).hexdigest() == before)
        assert record['originalFixtureUnchanged'], 'IME test altered the engine baseline fixture'
        return record
    except Exception as exc:
        primary = exc
        capture_failure(output, name, record, exc)
        retain_ime_focus_failure_diagnostics(record, process, keyboard)
        raise
    finally:
        if observer is not None:
            try:
                record['events'] = observer.events()
                if observer.restoration_required and api.user.IsWindow(observer.focus):
                    record['restoration'] = observer.command(4)
                    record['layoutRestored'] = observer.restored
            except Exception as exc:
                record.update(success=False, imeCleanupError=type(exc).__name__ + ': ' + str(exc))
            finally:
                record['imeCommands'] = observer.commands
                try: observer.close()
                except Exception as exc: record.update(success=False, hookCleanupError=str(exc))
        if keyboard is not None:
            try: keyboard.close(primary)
            except Exception as exc:
                record.update(success=False, keyboardCleanupError=type(exc).__name__ + ': ' + str(exc))
        retirement_failure = None
        if retirement is not None:
            try: retirement.close(primary)
            except Exception as exc:
                record.update(success=False, retirementCleanupError=type(exc).__name__ + ': ' + str(exc))
                if primary is None: retirement_failure = exc
        try: stop_owned_test_process(process, record)
        finally: write_result(output, name, record)
        if retirement_failure is not None: raise retirement_failure


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--suite', type=Path, required=True)
    parser.add_argument('--fixtures', type=Path)
    parser.add_argument('--readiness', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--verify-one', choices=dict(INPUT_CASES))
    parser.add_argument('--file', type=Path)
    parser.add_argument('--reopen-output', type=Path)
    args = parser.parse_args(argv)
    if os.name != 'nt' or not __debug__: raise RuntimeError('Actual native Windows execution with assertions enabled is required')
    suite = args.suite.resolve()
    inventory = json.loads((suite / 'suite-inventory.json').read_text(encoding='utf-8-sig'))
    assert isinstance(inventory, dict) and inventory.get('schemaVersion') == 1, 'Suite inventory identity is missing'
    architecture = native_arch.require_architecture(inventory.get('architecture'))
    controller = native_arch.validate_native_architecture(native_arch.observe_native_architecture(), architecture)
    if args.verify_one:
        assert args.file and args.reopen_output, 'The owned reopen fixture and receipt are required'
        observed = reopen_one(suite, args.file.resolve(), args.verify_one)
        with args.reopen_output.open('x', encoding='utf-8') as stream: json.dump(observed, stream, ensure_ascii=False, indent=2)
        return 0
    assert args.fixtures and args.readiness and args.output, 'Generated fixtures, readiness and fresh output are required'
    for path in (args.suite, args.fixtures, args.readiness, args.output):
        assert not path.is_symlink() and not getattr(path, 'is_junction', lambda: False)(), 'Linked test paths are not accepted'
    fixtures, output = args.fixtures.resolve(), args.output.resolve()
    assert suite != output and suite not in output.parents and fixtures != output and fixtures not in output.parents, 'Evidence must be outside the payload and baseline fixtures'
    assert not any(str(path).startswith(('\\\\', '//')) for path in (suite, fixtures, output)), 'Only local test paths are accepted'
    output.mkdir(parents=True, exist_ok=False)
    readiness = require_readiness(json.loads(args.readiness.read_text(encoding='utf-8-sig')), architecture=architecture)
    prepared_library = ascii_input.prepare_observer(output / 'ascii-observer-preparation', architecture=architecture)
    results = collect_cases([('ime-' + module, lambda module=module, extension=extension:
        case(suite, fixtures, output, readiness, module, extension, prepared_library=prepared_library)) for module, extension in INPUT_CASES], output)
    success = len(results) == 3 and all(row.get('success') is True and row.get('imeVerified') is True for row in results)
    report = {'schemaVersion': 1, 'kind': 'native-korean-ime', 'success': success,
              'imeVerified': success, 'suiteOnly': True, 'tests': results,
              'architecture': architecture, 'nativeArchitecture': controller,
              'expectedCaseCount': 3, 'passedCaseCount': sum(row.get('success') is True for row in results)}
    (output / 'results.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return 0 if success else 1


if __name__ == '__main__': raise SystemExit(main())
