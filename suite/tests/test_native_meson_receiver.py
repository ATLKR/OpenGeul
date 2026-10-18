"""Receiver contract tests; Linux results never qualify Windows execution."""
import importlib.util
import json
from pathlib import Path
import tempfile
import os
import sys
import unittest

RECEIVER = Path(__file__).resolve().parents[1] / "diagnostics/native-meson-receiver/receiver.py"
SETUP = ["setup", "--wrap-mode", "nofallback", "builddir", "-Ddefault_library=static",
         "-Dbuildtype=release", "-Dauto_features=disabled", "-Dcpp_std=c++20",
         "-Dtests=disabled", "-Dutilities=disabled", "-Dsubset=enabled",
         "-Draster=disabled", "-Dvector=disabled", "-Dicu=enabled",
         "-Dicu_builtin=true", "-Dgraphite2=enabled"]
COMPILE = ["compile", "-C", "builddir", "libs", "--verbose"]


def environment(candidate=False):
    return {"CC": '\"C:/Program Files/VS/cl.exe\"' if candidate else "/cygdrive/c/VS/cl.exe ",
            "CXX": '\"C:/Program Files/VS/cl.exe\"' if candidate else "/cygdrive/c/VS/cl.exe ",
            "PKG_CONFIG": "C:/tools/pkgconf-2.4.3.exe",
            "PKG_CONFIG_PATH": "C:/prefix pc;C:/graphite pc;C:/icu pc" if candidate
                               else "C:/prefix pc:C:/graphite pc:C:/icu pc",
            "PATH": "C:/native tools;C:/Windows", "CFLAGS": "-DKEEP=1"}


class ReceiverContracts(unittest.TestCase):
    def setUp(self):
        self.assertTrue(RECEIVER.is_file(), "native Meson receiver is not implemented")
        spec = importlib.util.spec_from_file_location("native_meson_receiver", RECEIVER)
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)

    def records(self, candidate=False):
        arm = "candidate" if candidate else "original"
        records = {stage: self.module.capture_record(arm, "capture", argv, environment(candidate),
                    {"pid": 12, "creationTimeRawTicks": "18446744073709551614"}, "C:/fixture " + arm)
                   for stage, argv in [("setup", SETUP), ("compile", COMPILE)]}
        records["compile"]["environment"]["PKG_CONFIG_PATH"] = environment()["PKG_CONFIG_PATH"]
        return records

    def test_capture_preserves_quoted_command_whitespace_raw_list_and_full_argv(self):
        record = self.module.capture_record("original", "capture", SETUP,
                    environment(), {"pid": 12}, "C:/fixture original")
        self.assertEqual(record["argv"], SETUP)
        self.assertEqual(record["environment"]["CC"], "/cygdrive/c/VS/cl.exe ")
        self.assertEqual(record["environment"]["PKG_CONFIG_PATH"], environment()["PKG_CONFIG_PATH"])
        self.assertFalse(record["fixtureExecutionAttempted"])
        with tempfile.TemporaryDirectory() as directory:
            path = self.module.save_capture(Path(directory), record)
            self.assertEqual(json.loads(path.read_text())["argv"], SETUP)
            with self.assertRaises(FileExistsError):
                self.module.save_capture(Path(directory), record)

    def test_parity_accepts_only_approved_environment_deltas_and_ignores_per_arm_cwd(self):
        result = self.module.compare_captures(self.records(), self.records(True))
        self.assertTrue(result["passed"])
        self.assertEqual(result["changedEnvironment"]["setup"], ["CC", "CXX", "PKG_CONFIG_PATH"])
        self.assertFalse(result["qualification"]["engineQualified"])

    def test_parity_rejects_missing_feature_extra_compile_flag_and_tool_identity_change(self):
        for mutate in [lambda r: r["setup"]["argv"].remove("-Dsubset=enabled"),
                       lambda r: r["compile"]["argv"].append("--clean"),
                       lambda r: r["setup"]["environment"].update(PKG_CONFIG="C:/different.exe"),
                       lambda r: r["compile"]["environment"].update(PATH="C:/injected"),
                       lambda r: r["compile"]["environment"].update(PKG_CONFIG_PATH="C:/changed")]:
            changed = self.records(True)
            mutate(changed)
            with self.assertRaises(ValueError):
                self.module.compare_captures(self.records(), changed)

    def test_parity_rejects_missing_compile_and_literal_quoted_path_list_entries(self):
        missing = self.records(True)
        del missing["compile"]
        with self.assertRaises(ValueError):
            self.module.compare_captures(self.records(), missing)
        changed = self.records(True)
        changed["setup"]["environment"]["PKG_CONFIG_PATH"] = '\"C:/prefix pc\";C:/graphite;C:/icu'
        with self.assertRaises(ValueError):
            self.module.compare_captures(self.records(), changed)

    def test_fixture_setup_keeps_generic_flags_and_reports_only_explicit_project_omissions(self):
        source = SETUP + ["-Dc_args=-DREAL_FLAG=1", "-Dcpp_args=/Z7", "-Db_vscrt=mdd"]
        executed, omitted = self.module.fixture_setup_argv(source)
        self.assertIn("-Dc_args=-DREAL_FLAG=1", executed)
        self.assertIn("-Dcpp_args=/Z7", executed)
        self.assertIn("-Db_vscrt=mdd", executed)
        self.assertIn("-Dbuildtype=release", executed)
        self.assertIn("-Dsubset=enabled", omitted)
        self.assertEqual([v for v in source if v not in omitted], executed)

    def test_fixture_setup_rejects_unknown_flags_and_cross_file_instead_of_dropping_them(self):
        for extra in [["-Dnew_feature=true"], ["--cross-file", "cross-file.txt"], ["--wipe"]]:
            with self.assertRaises(ValueError):
                self.module.fixture_setup_argv(SETUP + extra)

    def test_original_red_requires_exact_compiler_help_winerror2_and_ordinary_error_exit(self):
        compiler = "/cygdrive/c/VS/cl.exe"
        log = ("ERROR: Unknown compiler(s): [['" + compiler + "']]\n"
               "Running `" + compiler + " /?` gave \"[WinError 2] The system cannot find the file specified\"")
        self.assertTrue(self.module.is_original_compiler_red(1, log, compiler))
        for rc, output in [(0, log), (-1, log), (3221225477, log),
                           (1, log.replace("WinError 2", "WinError 5")),
                           (1, log.replace(" /?", " --version")),
                           (1, log.replace(compiler, "/cygdrive/c/OTHER/cl.exe")),
                           (1, "unrelated failed setup")]:
            self.assertFalse(self.module.is_original_compiler_red(rc, output, compiler))

    def test_capture_retains_pkgconf_protocol_and_compiler_override_environment(self):
        env = environment()
        env.update(PKG_CONFIG_LIBDIR="C:/library pc", PKG_CONFIG_MSVC_SYNTAX="present", CL="/DKEEP=1")
        record = self.module.capture_record("original", "capture", SETUP, env, {}, "C:/fixture")
        for key in ("PKG_CONFIG_LIBDIR", "PKG_CONFIG_MSVC_SYNTAX", "CL"):
            self.assertEqual(record["environment"].get(key), env[key])

    def test_pkg_query_restores_exact_captured_list_and_uses_direct_executable_argv(self):
        self.assertTrue(callable(getattr(self.module, "run_pkg_query", None)), "pkg-query runner is absent")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            script = root / "portable query fixture.py"
            script.write_text("import json,os,sys; print(json.dumps({'path':os.environ['PKG_CONFIG_PATH'], 'cc':os.environ['CC'], 'args':sys.argv[1:], 'syntax':os.environ.get('PKG_CONFIG_MSVC_SYNTAX')}))")
            env = environment(True)
            env["PKG_CONFIG"] = sys.executable
            capture = self.module.capture_record("candidate", "capture", SETUP, env, {}, str(root))
            current = dict(os.environ, PKG_CONFIG_PATH="wrong", PKG_CONFIG="wrong.exe", PKG_CONFIG_MSVC_SYNTAX="unexpected")
            receipt = self.module.run_pkg_query(capture, "candidate", [str(script), "argument with spaces"],
                    current, {"scope": "portable-test-only"}, root, "portable-query")
            output = json.loads(receipt["stdout"])
            self.assertEqual(receipt["pkgconfArgv"], [sys.executable, str(script), "argument with spaces"])
            self.assertEqual(output["path"], env["PKG_CONFIG_PATH"])
            self.assertEqual(output["cc"], env["CC"])
            self.assertEqual(output["args"], ["argument with spaces"])
            self.assertIsNone(output["syntax"])
            self.assertEqual(receipt["returncode"], 0)
            self.assertFalse(receipt["qualification"]["engineQualified"])
            self.assertEqual(json.loads((root / "candidate.pkg.portable-query.json").read_text())["receivedPath"], env["PKG_CONFIG_PATH"])

    def test_pkg_query_preserves_error_exit_and_rejects_wrong_arm_or_arbitrary_environment(self):
        self.assertTrue(callable(getattr(self.module, "run_pkg_query", None)), "pkg-query runner is absent")
        capture = self.records(True)["setup"]
        capture["environment"]["PKG_CONFIG"] = sys.executable
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            capture["cwd"] = str(root)
            receipt = self.module.run_pkg_query(capture, "candidate", ["-c", "import sys;sys.stderr.write('missing fixture');sys.exit(1)"],
                    dict(os.environ), {"scope": "portable-test-only"}, root, "missing")
            self.assertEqual(receipt["returncode"], 1)
            self.assertEqual(receipt["stderr"], "missing fixture")
            with self.assertRaises(ValueError):
                self.module.run_pkg_query(capture, "original", [], {}, {}, root, "wrong-arm")
            capture["environment"]["UNSELECTED_VARIABLE"] = "injection"
            with self.assertRaises(ValueError):
                self.module.run_pkg_query(capture, "candidate", [], {}, {}, root, "wrong-env")

    def test_pkg_query_runs_in_captured_cwd_to_resolve_the_same_relative_fixture(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture_root = root / "Dependency Fixtures"
            captured_cwd = fixture_root / "original observation"
            captured_cwd.mkdir(parents=True)
            graphite = fixture_root / "graphite"
            graphite.mkdir()
            (graphite / "marker.txt").write_text("same physical fixture")
            script = root / "portable cwd query.py"
            script.write_text("import json,os,pathlib; print(json.dumps({'cwd':os.getcwd(), 'value':pathlib.Path(os.environ['PKG_CONFIG_PATH']).read_text()}))")
            env = environment()
            env.update(PKG_CONFIG=sys.executable, PKG_CONFIG_PATH="../graphite/marker.txt")
            capture = self.module.capture_record("original", "capture", SETUP, env, {}, str(captured_cwd))
            receipt = self.module.run_pkg_query(capture, "original", [str(script)], dict(os.environ),
                    {"scope": "portable-test-only"}, root / "evidence", "relative-fixture")
            self.assertEqual(receipt["returncode"], 0, receipt["stderr"])
            output = json.loads(receipt["stdout"])
            self.assertEqual(Path(output["cwd"]), captured_cwd)
            self.assertEqual(output["value"], "same physical fixture")
            self.assertEqual(receipt["cwd"], str(captured_cwd))
            saved = json.loads((root / "evidence/original.pkg.relative-fixture.json").read_text())
            self.assertEqual(saved["cwd"], str(captured_cwd))
            self.assertEqual(saved["receivedPath"], "../graphite/marker.txt")

    def test_pkg_query_rejects_missing_relative_or_non_directory_captured_cwd(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            file_path = root / "ordinary file"
            file_path.write_text("not a directory")
            for index, cwd in enumerate([None, "", ".", str(root / "missing"), str(file_path)]):
                with self.subTest(cwd=cwd):
                    capture = self.records(True)["setup"]
                    capture["environment"]["PKG_CONFIG"] = sys.executable
                    if cwd is None:
                        del capture["cwd"]
                    else:
                        capture["cwd"] = cwd
                    with self.assertRaisesRegex(ValueError, "cwd"):
                        self.module.run_pkg_query(capture, "candidate", ["-c", "pass"],
                                dict(os.environ), {"scope": "portable-test-only"}, root, f"invalid-{index}")

    def test_compile_forwarding_is_exact_and_rejects_unscoped_commands(self):
        self.assertEqual(self.module.fixture_command(COMPILE), (COMPILE, []))
        for argv in [["install", "-C", "builddir"], COMPILE + ["--clean"], ["compile", "-C", "elsewhere", "libs"]]:
            with self.assertRaises(ValueError):
                self.module.fixture_command(argv)


if __name__ == "__main__":
    unittest.main()
