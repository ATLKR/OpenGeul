"""Reviewed source metadata; these selectors admit no runtime.

Consumers use these immutable expectations only alongside independently pinned
normal Full receipts, archives and native/CRT/Base/provider checks. Source-only
metadata never grants launch, model-reader or native input authority.
"""
from dataclasses import dataclass, field
from types import MappingProxyType

LEGACY_SOURCE=MappingProxyType(dict(version='26.8.1.1',
    coreCommit='bf6ef2662401c7d6dce671ab4deb26ee0af3a7c1',
    url='https://download.documentfoundation.org/libreoffice/src/26.8.1/libreoffice-26.8.1.1.tar.xz',
    size=302435508,sha256='296ba78e7ab0d381b94c3d6342f4ebb2320ee5097ca58781b9b744cab90b9785'))
NEW_SOURCE=MappingProxyType(dict(version='26.8.2.2',
    coreCommit='9dea406ab7695df6325b11b0e19fdca8db4b7276',
    url='https://download.documentfoundation.org/libreoffice/src/26.8.2/libreoffice-26.8.2.2.tar.xz',
    size=302823256,sha256='f0012302d9cc70955bd55890d3aaccf6c55677c4a6a46e1003f996b1b0dae8e7'))

@dataclass(frozen=True,slots=True)
class SourceContract:
    version: str
    core: str
    python_version: str
    firebird_version: str
    micro: str
    patch: str
    qualifies_runtime: bool=field(default=False,init=False)

LEGACY=SourceContract('26.8.1.1',LEGACY_SOURCE['coreCommit'],'3.13.15','3.0.13.33818-0','1','1')
NEW=SourceContract('26.8.2.2',NEW_SOURCE['coreCommit'],'3.13.17','3.0.14.33856-0','2','2')

def contract_for_source_pin(pin):
    if (type(pin) is not dict or set(pin)!=set(NEW_SOURCE)
            or type(pin['size']) is not int
            or any(type(pin[key]) is not str for key in ('version','coreCommit','url','sha256'))):
        raise ValueError('A closed exact authenticated source pin is required')
    if pin==dict(LEGACY_SOURCE):return LEGACY
    if pin==dict(NEW_SOURCE):return NEW
    raise ValueError('Source core/version/archive tuple is not reviewed')

def core_python_reader_path(pin):
    contract=contract_for_source_pin(pin)
    return 'Office/program/python-core-'+contract.python_version+'/bin/python.exe'

def fallback_identity_expectation(pin):
    contract=contract_for_source_pin(pin)
    configuration=dict(LIBO_VERSION_MAJOR='26',LIBO_VERSION_MINOR='8',
        LIBO_VERSION_MICRO=contract.micro,LIBO_VERSION_PATCH=contract.patch,LIBO_VERSION_SUFFIX='')
    return dict(rule='libreoffice-'+contract.version+'-installer-no-git-v1',
        configuration=configuration,build='2680',normalizedBuild='680',
        installerBuildId=contract.patch,buildid='680(Build:'+contract.patch+')')

@dataclass(frozen=True,slots=True)
class SourceOnlyExpectations:
    source_manifest_sha256: str
    native_targets_sha256: str
    hooks: tuple
    arm_guarded_count: int
    recipe_fields: object
    flex_fields: object
    winacc_fields: object
    qualifies_runtime: bool=field(default=False,init=False)

def new_source_only_expectations(pin,architecture):
    contract=contract_for_source_pin(pin)
    if contract is not NEW or type(architecture) is not str or architecture not in ('arm64','x64'):
        raise ValueError('Exact new source and reviewed native architecture are required')
    manifest='3c21739690aa8dc53c0b6a333aee81af845c9c913e11a9338948923d9fe24c89'
    targets='ba8d627adefb2dfe90e048546f6f55d54c8e739d0f4f21afbe8a556af54768bc'
    if architecture=='arm64':
        hooks=('arm64Full','winAccFocusOrder','flexFatalCompatibility')
        recipe_id='windows-arm64-v1';guarded=13
        recipe_sha='a8080687422c3160b568be282b14812247bb34008b345665fc60153440ea36bf'
    else:
        hooks=('moduleBootstrap','firebirdLoaderPath','zstdSourceLinks','gpgBuildCompilerPath',
               'atlNativePaths','harfbuzzNativeMesonPaths','cliPublisherPolicyPlatform',
               'winAccFocusOrder','flexFatalCompatibility')
        recipe_id='windows-x64-common-v2';guarded=4
        recipe_sha='95c0bff970c3cc13f679f2dbaa226c4c4a45e236195efcdcd25e6ade6f94b2dc'
    flags=dict(nativeBuildVerified=False,fullEngineQualified=False,acceptanceEligible=False,guiVerified=False)
    recipe=dict(schemaVersion=1,kind='native-engine-source-recipe-install',architecture=architecture,
        recipeId=recipe_id,policySha256=targets,manifestSha256=manifest,
        recipeSha256=recipe_sha,hookOrder=hooks,**flags)
    flex=dict(schemaVersion=1,kind='windows-flex-fatal-compatibility-source-hook',
        coreCommit=contract.core,architecture=architecture,path='connectivity/source/parse/sqlflex.l',
        beforeBytes=37027,afterBytes=37161,
        beforeSha256='87e66cc9306322ca97c2e4ccbb41b0960fb8857aee4e536bf051c043ebf6c11a',
        afterSha256='f0890c54e65b52ac31a37a99b20a17fb9e9282985f25fa99ba4718490975200c',**flags)
    winacc=dict(schemaVersion=1,kind='winacc-focus-order-source-patch',passed=True,
        coreCommit=contract.core,path='winaccessibility/source/service/AccObjectWinManager.cxx',
        beforeSha256='ab5ed31cac9b262461b1d7e45fbe4a5758fef852a0f51c08c0c6f8e25d1c9be0',
        afterSha256='5e5f42a6b448c0d9c70a05bf762e86951565b5a96decaf050399f577dd38332b',
        patchSha256='968379ba427ac952c5c7df7f0c37ceabb495310acc224ee5380d51f523fb3ed7',
        nativeBuildVerified=False,guiVerified=False,currentCiRootCauseConfirmed=False)
    return SourceOnlyExpectations(manifest,targets,hooks,guarded,MappingProxyType(recipe),
                                  MappingProxyType(flex),MappingProxyType(winacc))
