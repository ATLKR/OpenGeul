"""Exact diagnostic-only desktop preparation adapter; no Suite qualification."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import re
import stat
import sys


ROOT = Path(__file__).resolve().parents[1]
BRANCH = 'refs/heads/work/native35-arm64-input-witness'
WORKFLOW = 'ATLKR/OpenGeul/.github/workflows/suite-native35-input-witness.yml@' + BRANCH
ADDITIONAL_SOURCE_FILES = ('e2e/native35_input_witness_prepare.py',
    'suite/scripts/prepare-native35-input-witness.ps1', '.github/workflows/suite-native35-input-witness.yml',
    'suite/scripts/prepare-native31.ps1')
MAX_JSON = 256 * 1024


def require(value, message):
    if not value: raise ValueError(message)


def plain_path(path):
    path = Path(path)
    require(path.is_absolute() and '..' not in path.parts, 'Absolute unaliased diagnostic path required')
    for parent in (path, *path.parents):
        if parent.exists() or parent.is_symlink():
            info = parent.lstat()
            require(not stat.S_ISLNK(info.st_mode) and not getattr(info, 'st_file_attributes', 0) & 0x400,
                    'Linked/reparse diagnostic preparation path rejected')
    return path


def read_event():
    path = plain_path(os.environ['GITHUB_EVENT_PATH'])
    with path.open('rb') as stream: raw = stream.read(MAX_JSON + 1)
    require(len(raw) <= MAX_JSON, 'Event exceeds finite diagnostic bound')
    event = json.loads(raw)
    require(type(event) is dict, 'Actual diagnostic event object required')
    return event


def validate_context(env, event, platform):
    expected = dict(GITHUB_ACTIONS='true', RUNNER_ENVIRONMENT='github-hosted', RUNNER_OS='Windows',
        RUNNER_ARCH='ARM64', GITHUB_REPOSITORY='ATLKR/OpenGeul', GITHUB_EVENT_NAME='push',
        GITHUB_JOB='windows-suite', GITHUB_REF=BRANCH, GITHUB_WORKFLOW_REF=WORKFLOW,
        GITHUB_RUN_ATTEMPT='1', GITHUB_ACTOR='ATLKR', GITHUB_ACTOR_ID='65988341')
    require(platform == 'nt' and all(env.get(k) == v for k, v in expected.items()),
            'Exact hosted diagnostic owner-push context required')
    sha = env.get('GITHUB_SHA')
    require(type(sha) is str and re.fullmatch('[0-9a-f]{40}', sha) and sha != '0'*40
            and env.get('GITHUB_WORKFLOW_SHA') == sha and type(env.get('GITHUB_RUN_ID')) is str
            and re.fullmatch('[1-9][0-9]{0,19}', env['GITHUB_RUN_ID']), 'Diagnostic source/run identity mismatch')
    require(type(event) is dict, 'Actual diagnostic event object required')
    repository, sender = event.get('repository'), event.get('sender')
    require(type(repository) is dict and repository.get('full_name') == 'ATLKR/OpenGeul'
            and repository.get('private') is False and type(repository.get('id')) is int and repository['id'] > 0,
            'Actual public owned diagnostic repository required')
    require(type(sender) is dict and sender.get('login') == 'ATLKR' and type(sender.get('id')) is int
            and sender['id'] == 65988341 and sender.get('type') == 'User', 'Actual diagnostic owner sender required')
    require(event.get('ref') == BRANCH and event.get('deleted') is False and event.get('after') == sha,
            'Actual diagnostic push ref/deleted/after mismatch')


def load_control():
    spec = importlib.util.spec_from_file_location('native35_input_witness_control', ROOT / 'e2e/native31_desktop_control.py')
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def control_binding(core):
    return core.ControlBinding(BRANCH, WORKFLOW, 'windows-suite',
                               'e2e/native35_input_witness_prepare.py', ADDITIONAL_SOURCE_FILES)


def entry(args, *, platform=None):
    validate_context(os.environ, read_event(), os.name if platform is None else platform)
    require(args.prepare_privacy, 'Diagnostic action requires explicit preparation mode')
    require(args.observer == (args.deadline is not None), 'Observer/deadline arguments must be paired')
    core = load_control()
    # Preserve the core's only 120s deadline, owned observer, exact event/native/source
    # validation, classifier, privacy-only actions, limits, and raw receipts.
    return (core.observer if args.observer else core.controller)(args, binding=control_binding(core))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepare-privacy', action='store_true')
    parser.add_argument('--observer', action='store_true')
    parser.add_argument('--deadline', type=float)
    parser.add_argument('--output', type=Path, required=True)
    return entry(parser.parse_args())


if __name__ == '__main__':
    raise SystemExit(main())
