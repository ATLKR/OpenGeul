"""지원한 네이티브 Windows 아키텍처만 명시적으로 선택한다."""
import re
SUPPORTED_ARCHITECTURES = ('x64', 'arm64')
_TARGETS = {'x64': 'x86_64-pc-windows-msvc', 'arm64': 'aarch64-pc-windows-msvc'}
_MACHINES = {'x64': 0x8664, 'arm64': 0xAA64}


def require_architecture(value: str) -> str:
    if not isinstance(value, str) or value not in SUPPORTED_ARCHITECTURES:
        raise ValueError('지원한 Windows 아키텍처는 x64와 arm64입니다')
    return value


def target_triple(value: str) -> str:
    return _TARGETS[require_architecture(value)]


def machine_for(value: str) -> int:
    return _MACHINES[require_architecture(value)]


def component_artifact_name(role: str, run_id: str, architecture: str = 'x64') -> str:
    require_architecture(architecture)
    if role not in ('editor', 'cli') or not isinstance(run_id, str) or not re.fullmatch('[1-9][0-9]*', run_id):
        raise ValueError('구성 요소 역할과 실행 식별자가 올바르지 않습니다')
    suffix = '' if architecture == 'x64' else '-arm64'
    return f'opengeul-{role}-component{suffix}-{run_id}'
