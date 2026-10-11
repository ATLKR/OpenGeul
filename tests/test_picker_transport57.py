"""Pinned diagnostic transports reject substitution before any application runs."""
from pathlib import Path
import copy
from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import io
import json
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
import test_windows_components as component_fixtures

spec = importlib.util.spec_from_file_location("picker_transport57", ROOT / "probe/download-editor57.py")
transport = importlib.util.module_from_spec(spec)
spec.loader.exec_module(transport)


def archive(folder, destination):
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as output:
        for path in sorted(folder.rglob("*")):
            if path.is_file():
                output.write(path, path.relative_to(folder).as_posix())
    return destination


def pinned(path, name="synthetic", artifact_id=1, cap=64 * 1024 * 1024):
    return {"id": artifact_id, "name": name, "size": path.stat().st_size,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "expandedLimit": cap}


class PickerTransport57Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.run = {"id": transport.RUN_ID, "head_sha": transport.SOURCE, "run_attempt": 1,
                    "run_number": 57, "event": "push", "head_branch": "main",
                    "path": ".github/workflows/msix.yml", "status": "completed", "conclusion": "failure",
                    "repository": {"id": 42, "full_name": "ATLKR/OpenGeul", "private": False},
                    "head_repository": {"id": 42, "full_name": "ATLKR/OpenGeul", "private": False}}
        self.jobs = [{"id": 11 + index, "run_id": transport.RUN_ID, "name": name,
                      "status": "completed", "conclusion": "success"}
                     for index, name in enumerate(("wasm", "windows-editor"))]

    def metadata(self, spec):
        return {"id": spec["id"], "name": spec["name"], "size_in_bytes": spec["size"],
                "digest": "sha256:" + spec["sha256"], "expired": False,
                "expires_at": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
                "workflow_run": {"id": transport.RUN_ID, "head_sha": transport.SOURCE,
                                 "head_branch": "main", "repository_id": 42, "head_repository_id": 42}}

    def test_source_run_and_two_successful_jobs_are_required_despite_overall_failure(self):
        self.assertEqual(set(transport.validate_run(self.run, self.jobs)), {"wasm", "windows-editor"})
        for key, value in (("id", 1), ("head_sha", "a" * 40), ("run_attempt", 2),
                           ("run_number", 55), ("event", "workflow_dispatch"), ("head_branch", "other"),
                           ("path", ".github/workflows/other.yml"), ("status", "in_progress")):
            with self.subTest(key=key):
                changed = copy.deepcopy(self.run); changed[key] = value
                with self.assertRaises(ValueError): transport.validate_run(changed, self.jobs)
        for changed in ([self.jobs[0]], self.jobs + [self.jobs[1]],
                        [self.jobs[0], dict(self.jobs[1], conclusion="failure")],
                        [self.jobs[0], dict(self.jobs[1], run_id=1)]):
            with self.assertRaises(ValueError): transport.validate_run(self.run, changed)
        private = copy.deepcopy(self.run); private["repository"]["private"] = True
        with self.assertRaises(ValueError): transport.validate_run(private, self.jobs)
        for key, value in (("id", 0), ("full_name", "other/repo"), ("private", True)):
            changed = copy.deepcopy(self.run); changed["head_repository"][key] = value
            with self.assertRaises(ValueError): transport.validate_run(changed, self.jobs)

    def test_artifact_identity_digest_expiry_and_origin_cannot_be_substituted(self):
        spec = transport.ARTIFACTS["editor"]
        value = self.metadata(spec)
        transport.validate_artifact(value, spec, 42)
        for key, replacement in (("id", 1), ("name", "other"), ("size_in_bytes", 1),
                                 ("digest", "sha256:" + "0" * 64), ("expired", True),
                                 ("expires_at", "2000-01-01T00:00:00Z")):
            with self.subTest(key=key):
                changed = copy.deepcopy(value); changed[key] = replacement
                with self.assertRaises(ValueError): transport.validate_artifact(changed, spec, 42)
        for key, replacement in (("id", 1), ("head_sha", "a" * 40), ("repository_id", 0),
                                 ("head_repository_id", 0), ("head_branch", "other")):
            changed = copy.deepcopy(value); changed["workflow_run"][key] = replacement
            with self.assertRaises(ValueError): transport.validate_artifact(changed, spec, 42)

    def test_raw_size_and_digest_precede_zip_inventory_and_extraction(self):
        raw = self.root / "archive.zip"; raw.write_bytes(b"not a ZIP")
        spec = pinned(raw)
        for key, replacement in (("size", spec["size"] + 1), ("sha256", "0" * 64)):
            changed = dict(spec, **{key: replacement})
            with patch.object(transport, "inventory") as inspect:
                with self.assertRaises(ValueError):
                    transport.extract_verified_archive(raw, changed, self.root / "extracted")
                inspect.assert_not_called()
            self.assertFalse((self.root / "extracted").exists())

    def test_unsafe_symlink_and_expansion_archives_never_create_output(self):
        for kind in ("traversal", "symlink", "expanded"):
            with self.subTest(kind=kind):
                raw = self.root / (kind + ".zip")
                with zipfile.ZipFile(raw, "w") as output:
                    if kind == "traversal": output.writestr("../outside", b"x")
                    elif kind == "symlink":
                        entry = zipfile.ZipInfo("link")
                        entry.external_attr = (stat.S_IFLNK | 0o777) << 16
                        output.writestr(entry, "outside")
                    else: output.writestr("large", b"x" * 100)
                spec = pinned(raw, cap=99 if kind == "expanded" else 1024)
                with self.assertRaises(ValueError):
                    transport.extract_verified_archive(raw, spec, self.root / "extracted")
                self.assertFalse((self.root / "extracted").exists())
        self.assertFalse((self.root / "outside").exists())

    def inputs(self):
        fixture = component_fixtures.WindowsComponentsTests("test_same_run_components_restore_complete_payload_and_exact_ledger")
        fixture.setUp(); self.addCleanup(fixture.doCleanups)
        source = fixture.source()
        editor = self.root / "source-editor"
        env = {"GITHUB_REPOSITORY": transport.REPOSITORY, "GITHUB_SHA": transport.SOURCE,
               "GITHUB_RUN_ID": str(transport.RUN_ID), "GITHUB_RUN_ATTEMPT": "1"}
        fixture.helper().capture("editor", fixture.payload("editor"), source, editor, env=env)
        wasm = source / "apps/studio-host/vendor/rhwp-core"
        # The actual immutable transport has exactly six artifacts plus its source manifest.
        for name in set(path.name for path in wasm.iterdir()) - set(transport.wasm_artifacts.FILES) - {"OPEN_GEUL_WASM.json"}:
            (wasm / name).unlink()
        exe = editor / "payload/OpenGeul.exe"
        patches = (patch.object(transport, "EDITOR_SHA256", hashlib.sha256(exe.read_bytes()).hexdigest()),
                   patch.object(transport, "EDITOR_BYTES", exe.stat().st_size))
        for item in patches: item.start(); self.addCleanup(item.stop)
        return editor, wasm

    def test_full_component_inventory_source_ledger_and_wasm_parity_are_enforced(self):
        editor, wasm = self.inputs()
        verified = transport.validate_inputs(editor, wasm)
        self.assertEqual(verified["editorSha256"], transport.EDITOR_SHA256)
        self.assertEqual(set(verified["wasmArtifacts"]), set(transport.wasm_artifacts.FILES))
        path = wasm / "rhwp.js"; original = path.read_bytes(); path.write_bytes(original + b"changed")
        with self.assertRaisesRegex(ValueError, "digests"):
            transport.validate_inputs(editor, wasm)
        path.write_bytes(original)
        provenance = editor / "provenance.json"
        value = json.loads(provenance.read_text()); value["commit"] = "a" * 40
        provenance.write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError, "identity"):
            transport.validate_inputs(editor, wasm)

    def test_missing_or_extra_wasm_files_and_mismatched_exe_are_rejected(self):
        editor, wasm = self.inputs()
        (wasm / "extra.txt").write_text("extra")
        with self.assertRaisesRegex(ValueError, "inventory"): transport.validate_inputs(editor, wasm)
        (wasm / "extra.txt").unlink()
        with patch.object(transport, "EDITOR_SHA256", "0" * 64):
            with self.assertRaisesRegex(ValueError, "executable"): transport.validate_inputs(editor, wasm)
        original = (wasm / "LICENSE").read_bytes(); (wasm / "LICENSE").unlink()
        with self.assertRaisesRegex(ValueError, "inventory"): transport.validate_inputs(editor, wasm)
        (wasm / "LICENSE").write_bytes(original)

    def test_success_promotes_only_verified_inputs_and_never_executes_an_application(self):
        editor, wasm = self.inputs()
        archives = {"editor": archive(editor, self.root / "editor.zip"),
                    "wasm": archive(wasm, self.root / "wasm.zip")}
        specs = {role: pinned(path, "owned-" + role, 1 if role == "editor" else 2,
                              64 * 1024 * 1024 if role == "editor" else 33 * 1024 * 1024)
                 for role, path in archives.items()}
        metadata = {role: self.metadata(spec) for role, spec in specs.items()}
        def gh(endpoint):
            if endpoint.endswith(f"/runs/{transport.RUN_ID}"): return self.run
            if "/jobs?" in endpoint: return {"total_count": 2, "jobs": self.jobs}
            if "/artifacts?" in endpoint: return {"total_count": 2, "artifacts": list(metadata.values())}
            return metadata["editor" if endpoint.endswith("/1") else "wasm"]
        def download(spec, path):
            role = "editor" if spec["id"] == 1 else "wasm"
            shutil.copyfile(archives[role], path)
        target = self.root / "diagnostic"; target.mkdir()
        with patch.object(transport, "ARTIFACTS", specs), patch.object(transport, "gh_json", side_effect=gh), \
                patch.object(transport, "download_archive", side_effect=download), \
                patch.object(transport.subprocess, "run", side_effect=AssertionError("No application execution permitted")):
            value = transport.prepare(target)
        self.assertEqual(value["qualification"], "picker-diagnostic-only")
        self.assertFalse(value["qualifiedPackage"])
        self.assertEqual(value["sourceCommit"], transport.SOURCE)
        self.assertEqual(value["sourceRun"], transport.RUN_ID)
        self.assertEqual(value["wasmRebuild"]["artifacts"], value["wasmArtifacts"])
        self.assertTrue((target / "editor-input/payload/OpenGeul.exe").is_file())
        self.assertTrue((target / "fixture-hop/apps/studio-host/vendor/rhwp-core/rhwp_bg.wasm").is_file())
        self.assertFalse((target / "editor-input/payload/Tools").exists())
        self.assertLess((target / "evidence/source.json").stat().st_size, 8192)

    def test_ambiguous_artifacts_and_failed_job_block_downloads_and_execution(self):
        metadata = [self.metadata(spec) for spec in transport.ARTIFACTS.values()]
        for jobs, artifacts in ((self.jobs, metadata + [metadata[0]]),
                                ([self.jobs[0], dict(self.jobs[1], conclusion="failure")], metadata)):
            def gh(endpoint):
                if endpoint.endswith(f"/runs/{transport.RUN_ID}"): return self.run
                if "/jobs?" in endpoint: return {"total_count": len(jobs), "jobs": jobs}
                if "/artifacts?" in endpoint: return {"total_count": len(artifacts), "artifacts": artifacts}
                return metadata[0]
            with patch.object(transport, "gh_json", side_effect=gh), patch.object(transport, "download_archive") as download:
                with self.assertRaises(ValueError): transport.prepare(self.root)
                download.assert_not_called()
            self.assertFalse((self.root / "editor-input").exists())
            self.assertFalse((self.root / "fixture-hop").exists())

    def test_stale_destinations_and_escaping_receipt_precede_network_reads(self):
        with patch.object(transport, "gh_json") as gh:
            with self.assertRaises(ValueError):
                transport.prepare(self.root, self.root / ".." / "outside.json")
            gh.assert_not_called()
            (self.root / "editor-input").mkdir()
            with self.assertRaises(ValueError): transport.prepare(self.root)
            gh.assert_not_called()

    def test_github_error_output_and_redirects_are_never_exposed(self):
        result = subprocess.CompletedProcess([], 1, stdout=b"private document", stderr=b"SAS redirect secret")
        with patch.object(transport.subprocess, "run", return_value=result):
            with self.assertRaisesRegex(ValueError, "^GitHub metadata request failed$"):
                transport.gh_json("owned/api")
        with patch.object(transport, "prepare", side_effect=RuntimeError("SAS redirect secret")), \
                patch.object(sys, "argv", ["download-editor57.py"]), patch("sys.stderr", new_callable=io.StringIO) as error:
            self.assertEqual(transport.main(), 1)
            self.assertEqual(error.getvalue(), "Editor57 diagnostic input verification failed.\n")


if __name__ == "__main__":
    unittest.main()
