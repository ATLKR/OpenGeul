#!/usr/bin/env python3
"""Native Windows component receiver. Capture is parity evidence, never a build.

capture/recipe --evidence DIR --arm original|candidate [--meson FILE] -- ARGS
compare --original DIR --candidate DIR --output FILE
pkg-query --capture FILE --evidence DIR --arm original|candidate --name NAME -- ARGS

Only recipe executes Meson. The original recipe argv is always retained; the tiny
project omits an explicit list of HarfBuzz project options and keeps generic flags.
The external controller owns process deadlines, source pins, and qualification.
"""
from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

ENVIRONMENT_KEYS = (
    "CC", "CXX", "PKG_CONFIG", "PKG_CONFIG_PATH", "PATH", "AR", "LD", "NINJA",
    "CFLAGS", "CXXFLAGS", "CPPFLAGS", "LDFLAGS", "PYTHONHOME", "PYTHONPATH",
    "SYSTEMROOT", "INCLUDE", "LIB", "LIBPATH", "PYTHONWARNINGS", "CL", "_CL_",
    "LINK", "_LINK_", "CC_LD", "CXX_LD", "PKG_CONFIG_LIBDIR", "PKG_CONFIG_SYSROOT_DIR",
    "PKG_CONFIG_MSVC_SYNTAX",
)
PROJECT_OPTIONS = {
    "tests": "disabled", "utilities": "disabled", "subset": "enabled",
    "raster": "disabled", "vector": "disabled", "icu": "enabled",
    "icu_builtin": "true", "graphite2": "enabled",
}
GENERIC_OPTIONS = {
    "default_library", "buildtype", "auto_features", "cpp_std", "c_args",
    "cpp_args", "b_vscrt",
}


def qualification() -> dict:
    return {"componentReceiverFeasible": None, "harfbuzzSetupProven": False,
            "harfbuzzCompileProven": False, "engineQualified": False,
            "native23ExactRuntimeEquivalent": False}


def capture_record(arm: str, mode: str, argv: list[str], environ: dict,
                   identity: dict, cwd: str) -> dict:
    if arm not in ("original", "candidate") or mode not in ("capture", "recipe"):
        raise ValueError("unsupported arm or receiver mode")
    if not argv or argv[0] not in ("setup", "compile"):
        raise ValueError("only genuine setup/compile argv can be captured")
    return {"schemaVersion": 1, "scope": "component-receiver-only", "arm": arm,
            "mode": mode, "stage": argv[0], "argv": list(argv), "cwd": cwd,
            "environment": {key: environ.get(key) for key in ENVIRONMENT_KEYS},
            "identity": dict(identity), "fixtureExecutionAttempted": False,
            "qualification": qualification()}


def save_capture(directory: Path, record: dict) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / f"{record['arm']}.{record['mode']}.{record['stage']}.json"
    with target.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(record, stream, indent=2, ensure_ascii=False)
        stream.write("\n")
    return target


def fixture_setup_argv(argv: list[str]) -> tuple[list[str], list[str]]:
    if argv[:4] != ["setup", "--wrap-mode", "nofallback", "builddir"]:
        raise ValueError("setup must retain the approved wrap-mode and builddir invocation")
    executed, omitted, seen = list(argv[:4]), [], set()
    for arg in argv[4:]:
        match = re.fullmatch(r"-D([a-z0-9_]+)=(.*)", arg)
        if not match:
            raise ValueError(f"unapproved setup argument: {arg!r}")
        name, value = match.groups()
        if name in seen:
            raise ValueError(f"duplicate setup option: {name}")
        seen.add(name)
        if name in PROJECT_OPTIONS:
            if value != PROJECT_OPTIONS[name]:
                raise ValueError(f"unexpected HarfBuzz option value: {arg!r}")
            omitted.append(arg)
        elif name in GENERIC_OPTIONS:
            executed.append(arg)
        else:
            raise ValueError(f"unapproved setup option: {arg!r}")
    return executed, omitted


def fixture_command(argv: list[str]) -> tuple[list[str], list[str]]:
    if argv and argv[0] == "setup":
        return fixture_setup_argv(argv)
    if argv in (["compile", "-C", "builddir", "libs"],
                ["compile", "-C", "builddir", "libs", "--verbose"]):
        return list(argv), []
    raise ValueError("compile must retain exactly compile -C builddir libs [--verbose]")


def compare_captures(original: dict, candidate: dict) -> dict:
    if set(original) != {"setup", "compile"} or set(candidate) != {"setup", "compile"}:
        raise ValueError("complete setup and compile capture records are required")
    changes = {}
    for stage in ("setup", "compile"):
        left, right = original[stage], candidate[stage]
        if (left.get("arm"), right.get("arm"), left.get("mode"), right.get("mode")) != (
                "original", "candidate", "capture", "capture"):
            raise ValueError("parity accepts original/candidate capture-only records")
        if left.get("stage") != stage or right.get("stage") != stage:
            raise ValueError("capture stage does not match its file")
        if left["argv"] != right["argv"]:
            raise ValueError(f"complete {stage} argv parity failed")
        fixture_command(left["argv"])
        if set(left["environment"]) != set(ENVIRONMENT_KEYS) or set(right["environment"]) != set(ENVIRONMENT_KEYS):
            raise ValueError("capture environment key set is incomplete or changed")
        changed = [key for key in ENVIRONMENT_KEYS
                   if left["environment"][key] != right["environment"][key]]
        allowed = {"CC", "CXX", "PKG_CONFIG_PATH"} if stage == "setup" else {"CC", "CXX"}
        if set(changed) - allowed:
            raise ValueError(f"unapproved {stage} environment delta: {set(changed) - allowed}")
        if stage == "setup":
            if set(changed) != allowed:
                raise ValueError("setup requires all three demonstrated boundary conversions")
            for key in ("CC", "CXX"):
                before, after = left["environment"][key], right["environment"][key]
                if not isinstance(before, str) or not before.strip().startswith("/cygdrive/"):
                    raise ValueError(f"original {key} does not represent the demonstrated Cygwin boundary")
                if not isinstance(after, str) or not re.match(r'^"?[A-Za-z]:[/\\]', after):
                    raise ValueError(f"candidate {key} lacks a native Windows executable path")
            pathlist = right["environment"]["PKG_CONFIG_PATH"]
            if not isinstance(pathlist, str):
                raise ValueError("candidate dependency list is absent")
            entries = pathlist.split(";")
            if len(entries) < 3 or any(not entry or '"' in entry or "'" in entry or
                    not re.match(r"^[A-Za-z]:[/\\]", entry) for entry in entries):
                raise ValueError("candidate dependency list must contain raw native drive-path entries")
        changes[stage] = changed
    return {"schemaVersion": 1, "passed": True, "scope": "recipe-parity-only",
            "changedEnvironment": changes,
            "cwdBindings": {"original": {s: original[s]["cwd"] for s in original},
                            "candidate": {s: candidate[s]["cwd"] for s in candidate}},
            "qualification": qualification()}


def is_original_compiler_red(returncode: int, output: str, compiler: str) -> bool:
    if returncode != 1 or not re.fullmatch(r"/cygdrive/[^\s`]+/cl\.exe", compiler, re.IGNORECASE):
        return False
    unknown = re.search(r"ERROR: Unknown compiler\(s\):[^\n]*" + re.escape(compiler), output)
    running = re.search(r"Running `" + re.escape(compiler) +
                        r" /\?` gave \"\[WinError 2\] [^\n]*\"", output)
    return bool(unknown and running)


def run_pkg_query(capture: dict, arm: str, query_args: list[str], environ: dict,
                  identity: dict, evidence: Path, name: str) -> dict:
    if (capture.get("arm"), capture.get("mode"), capture.get("stage")) != (arm, "capture", "setup"):
        raise ValueError("pkg-query requires the selected arm's setup capture")
    captured = capture.get("environment", {})
    if set(captured) != set(ENVIRONMENT_KEYS) or any(
            value is not None and not isinstance(value, str) for value in captured.values()):
        raise ValueError("pkg-query accepts only the complete selected captured environment")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,60}", name):
        raise ValueError("query name must be one short filename component")
    executable = captured["PKG_CONFIG"]
    if not executable or executable != executable.strip() or any(c in executable for c in ('"', '\n', '\r', '\0')):
        raise ValueError("captured PKG_CONFIG must be a single unquoted executable pathname")
    if not isinstance(captured["PKG_CONFIG_PATH"], str):
        raise ValueError("captured dependency path-list string is absent")
    child_env = dict(environ)
    for key, value in captured.items():
        if value is None:
            child_env.pop(key, None)
        else:
            child_env[key] = value
    command = [executable, *query_args]
    evidence.mkdir(parents=True, exist_ok=True)
    stem = evidence / f"{arm}.pkg.{name}"
    target = stem.with_suffix(stem.suffix + ".json")
    stdout_path = stem.with_suffix(stem.suffix + ".stdout.log")
    stderr_path = stem.with_suffix(stem.suffix + ".stderr.log")
    receipt = {"schemaVersion": 1, "scope": "pkgconf-fixture-query-only", "arm": arm,
               "name": name, "pkgconfArgv": command, "receivedPath": child_env["PKG_CONFIG_PATH"],
               "environment": captured, "identity": dict(identity), "status": "started",
               "qualification": qualification()}
    with target.open("x", encoding="utf-8") as stream:
        json.dump(receipt, stream, indent=2, ensure_ascii=False)
        stream.write("\n")
    try:
        with stdout_path.open("xb") as stdout, stderr_path.open("xb") as stderr:
            completed = subprocess.run(command, env=child_env, stdout=stdout, stderr=stderr, check=False)
        raw_stdout, raw_stderr = stdout_path.read_bytes(), stderr_path.read_bytes()
        receipt.update(returncode=completed.returncode, status="exited",
                       stdout=raw_stdout.decode("utf-8", errors="replace"),
                       stderr=raw_stderr.decode("utf-8", errors="replace"),
                       stdoutPath=str(stdout_path), stderrPath=str(stderr_path),
                       stdoutSha256=hashlib.sha256(raw_stdout).hexdigest(),
                       stderrSha256=hashlib.sha256(raw_stderr).hexdigest())
        receipt["unexpectedTermination"] = completed.returncode < 0 or completed.returncode > 255
    except OSError as error:
        receipt.update(status="launch-error", error=str(error))
        target.write_text(json.dumps(receipt, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        raise
    target.write_text(json.dumps(receipt, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if receipt["unexpectedTermination"]:
        raise RuntimeError(f"pkgconf did not terminate with an ordinary exit: {receipt['returncode']}")
    return receipt


def native_identity() -> dict:
    if sys.platform != "win32":
        raise RuntimeError("runtime receiver requires native Windows ARM64 Python")
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetCurrentProcess.argtypes = []
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    kernel.IsWow64Process2.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.USHORT), ctypes.POINTER(wintypes.USHORT)]
    kernel.IsWow64Process2.restype = wintypes.BOOL
    kernel.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
    kernel.GetProcessTimes.restype = wintypes.BOOL
    handle = kernel.GetCurrentProcess()
    process, native = wintypes.USHORT(), wintypes.USHORT()
    if not kernel.IsWow64Process2(handle, ctypes.byref(process), ctypes.byref(native)):
        raise ctypes.WinError(ctypes.get_last_error())
    creation, exit_time, system, user = (wintypes.FILETIME() for _ in range(4))
    if not kernel.GetProcessTimes(handle, ctypes.byref(creation), ctypes.byref(exit_time), ctypes.byref(system), ctypes.byref(user)):
        raise ctypes.WinError(ctypes.get_last_error())
    identity = {"pid": os.getpid(), "processMachine": process.value, "nativeMachine": native.value,
                "creationTimeRawTicks": str((creation.dwHighDateTime << 32) | creation.dwLowDateTime),
                "nativeArm64": process.value == 0 and native.value == 0xAA64,
                "python": sys.executable, "pythonVersion": sys.version,
                "pythonSha256": hashlib.sha256(Path(sys.executable).read_bytes()).hexdigest()}
    if not identity["nativeArm64"]:
        raise RuntimeError("native Python identity required: " + json.dumps(identity))
    return identity


def execute_recipe(args: argparse.Namespace, record: dict, path: Path) -> int:
    forwarded, omitted = fixture_command(record["argv"])
    record["executedArgv"] = [sys.executable, str(Path(args.meson).resolve()), *forwarded]
    record["omittedProjectOptions"] = omitted
    record["fixtureExecutionAttempted"] = True
    record["status"] = "started"
    stage = record["stage"]
    stdout_path = args.evidence / f"{args.arm}.meson.{stage}.stdout.log"
    stderr_path = args.evidence / f"{args.arm}.meson.{stage}.stderr.log"
    record["stdoutPath"], record["stderrPath"] = str(stdout_path), str(stderr_path)
    path.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    with stdout_path.open("xb") as stdout, stderr_path.open("xb") as stderr:
        result = subprocess.run(record["executedArgv"], env=os.environ.copy(), stdout=stdout, stderr=stderr, check=False)
    log_path = Path("builddir/meson-logs/meson-log.txt")
    output = stdout_path.read_text(encoding="utf-8", errors="replace") + stderr_path.read_text(encoding="utf-8", errors="replace")
    if log_path.is_file():
        output += log_path.read_text(encoding="utf-8", errors="replace")
    red = args.arm == "original" and stage == "setup" and is_original_compiler_red(
        result.returncode, output, (record["environment"].get("CC") or "").strip())
    record["mesonReturncode"] = result.returncode
    record["classification"] = ("original-compiler-path-red" if red else
                                "fixture-stage-succeeded" if result.returncode == 0 else "unexpected-meson-failure")
    record["status"] = "exited"
    record["originalCompilerRed"] = red
    path.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"record": str(path), "classification": record["classification"], "mesonReturncode": result.returncode}))
    return result.returncode


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="mode", required=True)
    for mode in ("capture", "recipe"):
        command = commands.add_parser(mode)
        command.add_argument("--evidence", required=True, type=Path)
        command.add_argument("--arm", required=True, choices=("original", "candidate"))
        if mode == "recipe":
            command.add_argument("--meson", required=True, type=Path)
        command.add_argument("meson_args", nargs=argparse.REMAINDER)
    compare = commands.add_parser("compare")
    compare.add_argument("--original", required=True, type=Path)
    compare.add_argument("--candidate", required=True, type=Path)
    compare.add_argument("--output", required=True, type=Path)
    query = commands.add_parser("pkg-query")
    query.add_argument("--capture", required=True, type=Path)
    query.add_argument("--evidence", required=True, type=Path)
    query.add_argument("--arm", required=True, choices=("original", "candidate"))
    query.add_argument("--name", required=True)
    query.add_argument("query_args", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    if args.mode == "compare":
        records = {}
        for arm in ("original", "candidate"):
            directory = getattr(args, arm)
            records[arm] = {stage: json.loads((directory / f"{arm}.capture.{stage}.json").read_text(encoding="utf-8"))
                            for stage in ("setup", "compile")}
        result = compare_captures(records["original"], records["candidate"])
        with args.output.open("x", encoding="utf-8") as stream:
            json.dump(result, stream, indent=2)
            stream.write("\n")
        return 0
    if args.mode == "pkg-query":
        capture = json.loads(args.capture.read_text(encoding="utf-8"))
        query_args = args.query_args[1:] if args.query_args[:1] == ["--"] else args.query_args
        receipt = run_pkg_query(capture, args.arm, query_args, os.environ, native_identity(), args.evidence, args.name)
        print(json.dumps({"name": args.name, "returncode": receipt["returncode"], "scope": receipt["scope"]}))
        return receipt["returncode"]
    actual = args.meson_args[1:] if args.meson_args[:1] == ["--"] else args.meson_args
    record = capture_record(args.arm, args.mode, actual, os.environ, native_identity(), os.getcwd())
    record["receiverSha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    path = save_capture(args.evidence, record)
    if args.mode == "capture":
        print(json.dumps({"record": str(path), "scope": "parity-only", "fixtureExecuted": False}))
        return 0
    return execute_recipe(args, record, path)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, RuntimeError) as error:
        print(json.dumps({"scope": "component-receiver-only", "status": "receiver-error", "error": str(error)}), file=sys.stderr)
        raise SystemExit(1)
