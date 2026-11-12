"""Synthetic current-producer metadata only; never use on real artifacts."""
import ctypes

def current_command_fixture(row, ime):
    assert type(row) is dict and row['policyVersion']==4 and row['nativeContext']['version']==4
    row['policyVersion']=5;row['nativeSnapshotBytes']=ctypes.sizeof(ime.NativeState)
    language={name:0 for name,_ in ime.NativeProfileLanguageRecord._fields_};row['profileLanguage']=language
    number=row['command']
    if number in (1,4):
        language.update(schemaVersion=1,command=number,complete=1,originalLanguage=0x409,observedBefore=0x409,
            interfaceAttempts=1,getterAttempts=1 if number==1 else 2,observedMask=3 if number==1 else 19)
        if number==4:language['observedAfterHkl']=0x409
    return row

def current_record_fixture(record, ime):
    assert record['imePolicyVersion']==4
    record['imePolicyVersion']=5;record['imePolicySourceSha256']=ime.profile_policy_source_sha256()
    for row in record['imeCommands']:current_command_fixture(row,ime)
    return record

def current_diagnostic_context_fixture(record, ime):
    # The legacy prefix fixture intentionally omits full language/restoration
    # evidence. Add only current transport context; it still cannot qualify IME.
    assert 'imeCompartmentDiagnostics' in record and type(record['imeCommands']) is list
    record['imePolicyVersion']=5;record['imePolicySourceSha256']=ime.profile_policy_source_sha256()
    for row in record['imeCommands']:
        assert row['nativeContext']['version']==4 and row.get('policyVersion',4)==4
        row['policyVersion']=5;row['nativeSnapshotBytes']=ctypes.sizeof(ime.NativeState)
    return record
