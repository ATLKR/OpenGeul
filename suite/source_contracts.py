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

@dataclass(frozen=True,slots=True)
class SourceCompanionIntent:
    core: str
    architecture: str
    path: str
    role: str
    qualifies_runtime: bool=field(default=False,init=False)

_SPSUPP_INTENT=SourceCompanionIntent(NEW.core,'x64','program/spsupp_x86.dll','x86CompatibilityHelper')

def source_companion_intent(pin,architecture):
    """Source intent only; no compiled bytes, receipt or runtime is admitted."""
    if (contract_for_source_pin(pin) is not NEW or type(architecture) is not str
            or architecture!='x64'):
        raise ValueError('Source companion intent requires the exact reviewed x64 source profile')
    return _SPSUPP_INTENT

@dataclass(frozen=True,slots=True)
class SourceTwainIntent:
    core: str
    architecture: str
    path: str
    role: str
    kind: str
    source_intent: str
    qualifies_runtime: bool=field(default=False,init=False)

_TWAIN_INTENT=SourceTwainIntent(NEW.core,'x64','program/twain32shim.exe','x86CompatibilityHelper',
    'source-built-x86-twain-companion','twain-32bit-driver-process-bridge')

def source_twain_intent(pin,architecture):
    """Separate TWAIN source intent; compiled bytes still require Full admission."""
    if (contract_for_source_pin(pin) is not NEW or type(architecture) is not str
            or architecture!='x64'):
        raise ValueError('TWAIN source intent requires the exact reviewed x64 source profile')
    return _TWAIN_INTENT

def fallback_identity_expectation(pin):
    contract=contract_for_source_pin(pin)
    configuration=dict(LIBO_VERSION_MAJOR='26',LIBO_VERSION_MINOR='8',
        LIBO_VERSION_MICRO=contract.micro,LIBO_VERSION_PATCH=contract.patch,LIBO_VERSION_SUFFIX='')
    return dict(rule='libreoffice-'+contract.version+'-installer-no-git-v1',
        configuration=configuration,build='2680',normalizedBuild='680',
        installerBuildId=contract.patch,buildid='680(Build:'+contract.patch+')')


def dotnet_project_graph_expectation(pin):
    """Exact source metadata only; no build output or runtime is qualified."""
    if contract_for_source_pin(pin) is not NEW:
        raise ValueError('.NET project graph expectations require the exact reviewed new source')
    return dict(schemaVersion=1,coreCommit=NEW.core,sources=[
        dict(path='solenv/gbuild/DotnetLibrary.mk',size=5315,
            sha256='f4d2e54af51037267b4027461d7caa6c7a22d3660b99bedeb68f2160d46f476b',
            afterSize=5728,afterSha256='cc1e4a62d0d97681b1742ada794af15945e465af86d4d2f54b38b245c8889db3'),
        dict(path='solenv/gbuild/DotnetTest.mk',size=5154,
            sha256='5391ab97bd1a43c71584afd2819499c1fca75ab95a2e35835dc7e10a02813272',
            afterSize=5555,afterSha256='09987ad29eb2afac9f2ff7a973bd2b7c32ccd54f286a4281610b5bc89fe939f7')])

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
    manifest='9bf183e354ee1f68158233bad959ac8a756c3e667cb0892760b98c44aabb8e50'
    targets='ba8d627adefb2dfe90e048546f6f55d54c8e739d0f4f21afbe8a556af54768bc'
    if architecture=='arm64':
        hooks=('arm64Full','winAccFocusOrder','flexFatalCompatibility','dotnetProjectGraph')
        recipe_id='windows-arm64-v1';guarded=13
        recipe_sha='9b10511f31066a5966014c6357268b4d1dcfa3ffa24eb9c97c8bc0c05dbef0fe'
    else:
        hooks=('moduleBootstrap','firebirdLoaderPath','zstdSourceLinks','gpgBuildCompilerPath',
               'atlNativePaths','harfbuzzNativeMesonPaths','cliPublisherPolicyPlatform',
               'winAccFocusOrder','flexFatalCompatibility','dotnetProjectGraph')
        recipe_id='windows-x64-common-v2';guarded=4
        recipe_sha='66704ff304812a3181912c38723e4d0333670055dbb0c879e46fcc1ea961324d'
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
