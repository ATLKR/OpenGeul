"""Closed numeric failure evidence; never an acceptance or error-text channel."""
import json
import sys
import types


def _traceback(error):
    return BaseException.__traceback__.__get__(error)


def emit_failure(error, entry_code, source_codes):
    try:
        if type(entry_code) is not int or entry_code not in (1, 2):
            return False
        if type(source_codes) is not tuple or len(source_codes) > 16:
            return False
        for row in source_codes:
            if type(row) is not tuple or len(row) != 2:
                return False
            code, file_code = row
            if type(code) is not types.CodeType or type(file_code) is not int or file_code not in (1, 2, 3):
                return False
        exception_code = 0
        for exception_type, number in ((ValueError, 1), (AssertionError, 2), (RuntimeError, 3), (TimeoutError, 4), (FileNotFoundError, 5), (PermissionError, 6), (OSError, 7), (TypeError, 8), (KeyError, 9), (ImportError, 10), (json.JSONDecodeError, 11)):
            if type(error) is exception_type:
                exception_code = number
                break
        frames = []
        unknown = 0
        truncated = 0
        walked = 0
        traceback = _traceback(error)
        while traceback is not None and walked < 32:
            walked += 1
            frame_code = traceback.tb_frame.f_code
            file_code = 0
            for known_code, number in source_codes:
                if frame_code is known_code:
                    file_code = number
                    break
            if not file_code:
                unknown += 1
            elif len(frames) == 12:
                truncated = 1
            else:
                line = traceback.tb_lineno
                if type(line) is not int or not 1 <= line <= 2147483647:
                    return False
                frames.append({'sourceFileCode': file_code, 'line': line})
            traceback = traceback.tb_next
        if traceback is not None:
            truncated = 1
        record = {'schemaVersion': 1, 'entryCode': entry_code, 'exceptionCode': exception_code, 'diagnosticOnly': 1, 'acceptanceEligible': 0, 'unknownFrameCount': unknown, 'truncated': truncated, 'frames': frames}
        payload = json.dumps(record, ensure_ascii=True, separators=(',', ':')) + '\n'
        if type(payload) is not str or not payload.isascii() or len(payload.encode('ascii')) > 4096:
            return False
        written = sys.stderr.write(payload)
        return type(written) is int and written == len(payload)
    except BaseException:
        return False
