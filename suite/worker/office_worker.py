"""UTF-8 JSONL host for a single private Office document session."""
import argparse
import json
from pathlib import Path
import sys
import threading

from session import DocumentSession, FACTORIES, WorkerError

MAX_REQUEST_BYTES = 1024 * 1024


def load_modules(path):
    try:
        manifest = json.loads(Path(path).read_text(encoding='utf-8-sig'))
        modules = manifest['modules']
        if type(manifest.get('schemaVersion')) is not int or manifest['schemaVersion'] != 1 or not isinstance(modules, dict):
            raise ValueError('schema')
        for key, module in modules.items():
            if key == 'hwp':
                continue
            if key not in FACTORIES or module.get('factory') != FACTORIES[key]:
                raise ValueError('factory')
            exts, filters = module['extensions'], module['filters']
            if not isinstance(exts, list) or not exts or not isinstance(filters, dict):
                raise ValueError('formats')
            if any(not isinstance(ext, str) or not ext.isalnum() or ext != ext.lower() for ext in exts):
                raise ValueError('extension')
            if any(not isinstance(ext, str) or ext not in exts or not isinstance(value, str) or not value
                   for ext, value in filters.items()):
                raise ValueError('filter')
            if set(exts) != set(filters):
                raise ValueError('missing filter')
        if not any(key in FACTORIES for key in modules):
            raise ValueError('empty')
        return modules
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        raise WorkerError('invalid_manifest', 'Office 제품 설정을 읽을 수 없습니다.') from exc


def handle_request(session, request):
    request_id = request.get('id') if isinstance(request, dict) else None
    if type(request_id) not in (int, str):
        request_id = None
    try:
        if (not isinstance(request, dict) or set(request) != {'id', 'command', 'args'}
                or type(request_id) not in (int, str) or not isinstance(request['command'], str)
                or not isinstance(request['args'], dict)):
            raise WorkerError('invalid_request', 'id, command, args 객체를 포함한 요청이 필요합니다.')
        result = session.dispatch(request['command'], request['args'])
        return {'id': request_id, 'ok': True, 'result': result}
    except WorkerError as exc:
        return {'id': request_id, 'ok': False, 'error': {'code': exc.code, 'message': exc.message}}
    except Exception:
        return {'id': request_id, 'ok': False,
                'error': {'code': 'engine_error', 'message': 'Office 작업에 실패했습니다. 문서 상태를 확인해 주세요.'}}


def serve(session, incoming, outgoing):
    write_lock = threading.Lock()

    def write_message(message):
        encoded = json.dumps(message, ensure_ascii=False, allow_nan=False) + '\n'
        with write_lock:
            outgoing.write(encoded)
            outgoing.flush()

    session.event_sink = write_message
    while session.state != 'stopped':
        line = incoming.readline(MAX_REQUEST_BYTES + 1)
        if not line:
            # EOF is never authorization to discard an unsaved document.
            session.dispatch('shutdown', {'discard': False})
            return
        try:
            if len(line.encode('utf-8')) > MAX_REQUEST_BYTES:
                while line and not line.endswith('\n'):
                    line = incoming.readline(MAX_REQUEST_BYTES + 1)
                raise WorkerError('request_too_large', '작업자 요청이 너무 큽니다.')
            request = json.loads(line)
            response = handle_request(session, request)
        except (ValueError, WorkerError) as exc:
            code = exc.code if isinstance(exc, WorkerError) else 'invalid_json'
            response = {'id': None, 'ok': False, 'error': {'code': code, 'message': 'JSON 요청을 읽을 수 없습니다.'}}
        write_message(response)


def main(argv=None):
    parser = argparse.ArgumentParser(description='OpenGeul Office document worker')
    parser.add_argument('--runtime', required=True, type=Path)
    parser.add_argument('--manifest', type=Path)
    args = parser.parse_args(argv)
    if hasattr(sys.stdin, 'reconfigure'):
        sys.stdin.reconfigure(encoding='utf-8', errors='strict')
        sys.stdout.reconfigure(encoding='utf-8', errors='strict', line_buffering=True)
    root = Path(__file__).resolve().parent.parent
    manifest = args.manifest or root / 'suite-product.json'
    if args.manifest is None and not manifest.is_file():
        manifest = root / 'config' / 'product.json'
    try:
        modules = load_modules(manifest)
        session = DocumentSession(args.runtime.resolve(), modules)
        serve(session, sys.stdin, sys.stdout)
        return 0 if session.state == 'stopped' else 2
    except WorkerError as exc:
        sys.stdout.write(json.dumps({'id': None, 'ok': False,
                                    'error': {'code': exc.code, 'message': exc.message}}, ensure_ascii=False) + '\n')
        sys.stdout.flush()
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
