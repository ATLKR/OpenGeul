# Fixed read-only schema v1

This is not RequestV2/PhaseWitness/ExpectedDataRoots. It cannot authorize a phase, adopt roots or service a package.

Expected input to Python `ExpectedObservation.from_data(value)` is exactly:
- schemaVersion=1, kind="source-only-packaged-context-expectation"
- packageFullName, packageFamilyName: bounded nonempty ASCII package identifiers; userSid: S-1-5-*; architecture=x64|arm64.
- sourceRecipe: exact seven keys formatVersion=1,identifier="org.allenlabs.opengeul",tauriConfigSha256,webviewManagerSha256,pathResolverSha256 (lowercase64hex),appDirectoriesOverride=null,dataDirectory=null.
- logicalPaths: exactly productLocalData,productRoamingData, independent absolute local Windows paths, max1024 UTF-16 code units each, no UNC/device/ADS/.., only ASCII A-Z folded for equality; Unicode spelling preserved without case substitution.
- clock: exactly startQpc,phaseDeadlineQpc,observerDeadlineQpc,qpcFrequency positive exact integers; start < observerDeadline <= min(phaseDeadline,start+10*frequency), phaseDeadline<=start+90*frequency.
- sourceBundleSha256: external lowercase64hex source-only bundle SHA.

`ExpectedObservation.sha256` is SHA256 of canonical JSON (sort_keys,separators(',',':'),ensure_ascii=True,allow_nan=False). This digest is structural, not an installed-package attestation.

Successful observation projection exact keys:
schemaVersion=1, kind="packaged-context-readonly-observation", observationComplete=true,failureCode=0, simulationOnly=bool,
actualWindowsExecuted=false,qualification=false,canService=false,originalHelperHandleKnown=false,controllerOwnershipKnown=false,durableLease=false,watchdogVerified=false,osImplicitEffectsKnown=false,createdByThisRun=false,preexistingAdopted=false,
requestSha256,sourceBundleSha256,
package={fullName,familyName,userSid,pid,createdFileTime,nativeMachine,processMachine},
knownFolders={localAppData,roamingAppData},
directories={productLocalData,productRoamingData,localState},
clock={startedQpc,finishedQpc,deadlineQpc,qpcFrequency},
allDirectoryHandlesHeldTogether=true,processGenerationRechecked=true.

Every directory exact keys: logicalPath,finalPath (absolute local path max1024 UTF-16 code units),volumeSerial(uint64 incl0),fileId(nonzero32lowerhex),creationFileTime(positive uint64),desiredAccess=128,shareMode=7,openDisposition=3,reparse=false,handleRetainedDuringObservation=true,handleClosed=true. All three (volumeSerial,fileId) pairs differ. Product logical paths match independent expectation and observed KnownFolder/identifier; LocalState logicalPath is the WinRT-returned path (not inferred from PFN). Final paths must always be present; they may differ from logical paths because package virtualization is observed rather than guessed. Native implementation rejects reparse components and repeats open/identity checks. There is no master-view equality or actual-browser UDF proof here.

Package FullName/PFN/SID/native machine match expectation; nativeMachine x64=34404 or arm64=43620, processMachine=0; pid/creation positive integers. Clock has expected frequency/deadline, started>=expected start and finished>=started and <observerDeadline. Request/source bundle digest exact expected values. Successful API projection is only metadata: never set execution/ownership/qualification flags or synthesize a phase witness.

Failure record exact keys: schemaVersion=1,kind="packaged-context-readonly-failure",failureCode integer1..31,observationComplete=false,simulationOnly=bool, all ten authority/origin flags above false. No package, roots or partial identity payload. Error text/argv/env/paths from failures never emitted.

`validate_observation(record,expected)` accepts complete metadata only, otherwise raises a closed ContractError. `as_phase_witness(...)` always raises `OBSERVATION_IS_NOT_PHASE_AUTHORITY`. `run_native(...)` always raises `OWNED_LAUNCH_AND_WATCHDOG_UNVERIFIED`.

Bundle contract: `validate_bundle(root,raw,expected_sha256)` independently verifies raw SHA before parsing; exact {schemaVersion=1,kind="packaged-context-source-bundle",files:[{path,bytes,sha256}]} ; 1..16 relative unique-case exact file paths, no .. /backslash/colon/absolute aliases; exact actual production path set passed as `expected_paths` required kwarg. Each 1..512KiB, total<=2MiB, regular no symlink/reparse/hardlink in path chain, byte/hash pre/post stable. All current production files must be listed; unknown/missing/extra files relative to explicit expected_paths reject. Canonical bundle SHA is not a native executable hash or package qualification. Tests may use synthetic source bundles clearly labeled source-only.
