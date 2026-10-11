"""Production Windows password qualification; public synthetic documents only.

Uses the frozen source checkout's existing Session, actual WebView controls and
owned native HWNDs. Does not call app test APIs or change the original E2E suite.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import traceback
import xml.etree.ElementTree as ET
import zipfile

EXPECTED_SOURCE = "756116ff1fc094e8a1bdf2ecec6fcf3f6d3c4e17"
EXPECTED_RUN = "38142625600"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def simple_file(folder: Path, name: str) -> Path:
    require(isinstance(name, str) and name not in ("", ".", "..")
            and not any(c in name for c in "/\\:"), "Fixture must be a basename")
    path = folder / name
    require(path.is_file() and not path.is_symlink(), f"Missing regular fixture: {name}")
    return path


class Qualification:
    def __init__(self, args):
        self.args = args
        self.root = args.source_root.resolve()
        self.fixtures = args.fixtures.resolve()
        self.output = args.output.resolve()
        self.exe = args.exe.resolve()
        require(os.name == "nt", "Actual native qualification requires Windows")
        require(not self.output.exists(), "Refusing to replace existing evidence")
        self.output.mkdir(parents=True)
        sys.path.insert(0, str(self.root / "e2e"))
        from driver import Session, edit, menu, until
        from hwpx_oracle import inspect_hwpx
        from native_controls import bind_dialog, dismiss_error_dialog
        from prepare_payload import inventory, stream_hash, verify_checksums
        from uia_snapshot import snapshot_descendants
        self.Session, self.edit, self.menu, self.until = Session, edit, menu, until
        self.inspect_hwpx = inspect_hwpx
        self.bind_dialog, self.dismiss_error = bind_dialog, dismiss_error_dialog
        self.snapshot = snapshot_descendants
        self.manifest = json.loads((self.fixtures / "manifest.json").read_text(encoding="utf-8"))
        engine = self.manifest["engine"]
        require(engine["qualification"] == "final-source-bound", "Preliminary WASM cannot qualify the final payload")
        expected = {
            "upstream": json.loads((self.root / "config/upstream.lock.json").read_text()),
            "namespaceHelper": sha(self.root / "overlay/hwpx_namespaces.rs"),
            "namespacePatcher": sha(self.root / "scripts/patch_namespaces.py"),
        }
        for key, value in expected.items():
            require(engine["provenance"].get(key) == value, f"Fixture source binding differs: {key}")
        require(engine["wasmSha256"] == engine["provenance"]["artifacts"]["rhwp_bg.wasm"], "Fixture WASM hash mismatch")
        require(engine["jsSha256"] == engine["provenance"]["artifacts"]["rhwp.js"], "Fixture JS hash mismatch")
        self.password = self.manifest["password"]
        self.expected_text = self.manifest["expectedText"]
        self.prior_text = self.manifest["priorExpectedText"]
        require(self.password == "OpenGeul-native-123456", "Expected public QA password")
        require(self.expected_text and self.prior_text and self.expected_text != self.prior_text,
                "Encrypted and prior documents need distinct owned content")
        self.prior = simple_file(self.fixtures, self.manifest["priorPath"])
        require(sha(self.prior) == self.manifest["prior"]["sha256"]
                and self.prior.stat().st_size == self.manifest["prior"]["bytes"], "Prior fixture changed")
        require(self.inspect_hwpx(self.prior)["text"] == self.prior_text, "Prior document oracle mismatch")
        require(self.manifest["independentVerification"]["passed"] is True,
                "Generator independent ciphertext verification did not pass")
        self.sources = {}
        for item in self.manifest["fixtures"]:
            require(item["format"] in ("hwp", "hwpx") and item["format"] not in self.sources, "Unexpected fixture set")
            require(all(item.get(key) is True for key in ("normalOpenRejected", "wrongPasswordRejected", "correctPasswordTextVerified")),
                    "Encrypted fixture lacks normal/wrong/correct password controls")
            path = simple_file(self.fixtures, item["path"])
            require(sha(path) == item["sha256"] and path.stat().st_size == item["bytes"], "Ciphertext fixture changed")
            self.sources[item["format"]] = (path, item["sha256"])
        require(set(self.sources) == {"hwp", "hwpx"}, "Both encrypted formats are required")
        package = self.root / "package"
        verify_checksums(package)
        provenance = json.loads((package / "provenance.json").read_text())
        require(provenance["repository"] == "ATLKR/OpenGeul", "Unexpected package repository")
        require(provenance["commit"] == args.expected_source and str(provenance["runId"]) == args.expected_run,
                "Package is not the requested final source/run")
        require(provenance.get("upstream") == expected["upstream"], "Package upstream pins differ from the checked-out source")
        require(provenance.get("sourceParity", {}).get("wasmRebuild") == engine["provenance"],
                "Fixture engine differs from the final native payload's recorded rebuilt WASM")
        archives = list(package.glob("*portable.zip"))
        require(len(archives) == 1, "Exactly one verified portable payload is required")
        with zipfile.ZipFile(archives[0]) as archive:
            runtime_hashes = {}
            for name, entry in inventory(archive).items():
                with archive.open(entry) as source:
                    expected_hash = stream_hash(source)
                runtime_path = self.exe.parent.joinpath(*name.split("/"))
                require(runtime_path.is_file() and not runtime_path.is_symlink()
                        and sha(runtime_path) == expected_hash, f"Runtime file differs from verified portable payload: {name}")
                runtime_hashes[name] = expected_hash
        expected_exe = runtime_hashes["OpenGeul.exe"]
        require(self.exe.name == "OpenGeul.exe", "Expected the actual final runtime editor")
        self.identity = {"sourceCommit": args.expected_source, "buildRunId": args.expected_run,
                         "editorSha256": expected_exe, "fixtureManifestSha256": sha(self.fixtures / "manifest.json"),
                         "runtimeFilesVerified": len(runtime_hashes), "cliSha256": runtime_hashes["Tools/rhwp.exe"],
                         "engine": engine}
        (self.output / "identity.json").write_text(json.dumps(self.identity, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        self.records = []
        self.oracle_count = 0

    def unchanged(self, encrypted: Path, expected: str):
        require(sha(encrypted) == expected, "Protected source bytes changed")

    def session(self, name: str, source_format: str):
        folder = self.output / name
        folder.mkdir()
        prior = folder / "prior.hwpx"
        protected = folder / f"protected.{source_format}"
        shutil.copyfile(self.prior, prior)
        original, checksum = self.sources[source_format]
        shutil.copyfile(original, protected)
        self.unchanged(protected, checksum)
        session = self.Session("native", folder / "session", prior, executable=self.exe)
        try:
            require(session.page.evaluate("typeof window.__wasm === 'undefined' && typeof window.__inputHandler === 'undefined'"),
                    "Production payload exposes a development bridge")
        except BaseException:
            session.close()
            raise
        return folder, prior, protected, checksum, session

    def password_dialog(self, session):
        dialog = session.page.get_by_role("dialog", name="문서 암호 입력", exact=True)
        dialog.wait_for(state="visible", timeout=30000)
        require(dialog.count() == 1, "Expected one password dialog")
        return dialog

    def open_protected(self, session, protected: Path):
        self.menu(session.page, "file:open")
        session.native_dialog(protected)
        return self.password_dialog(session)

    def wrong_password(self, session, dialog):
        dialog.locator("#hwp-password-input").fill("OpenGeul-wrong-123456")
        dialog.locator("#hwp-password-input").press("Enter")
        dialog = self.password_dialog(session)
        error = dialog.locator("#hwp-password-error")
        error.wait_for(state="visible", timeout=30000)
        message = error.inner_text()
        require("다시 입력" in message, "Wrong password did not offer retry")
        require(dialog.locator("#hwp-password-input").input_value() == "", "Retry retains prior password")
        return dialog, message

    def retry_cancel(self, source_format: str):
        folder, prior, protected, checksum, session = self.session(f"retry-cancel-{source_format}", source_format)
        try:
            previous_sha = sha(prior)
            dialog = self.open_protected(session, protected)
            dialog, retry_message = self.wrong_password(session, dialog)
            require(prior.name in session.page.title(), "Wrong password replaced prior document title")
            session.page.screenshot(path=str(folder / "retry-visible.png"))
            dialog.get_by_role("button", name="취소", exact=True).click()
            dialog.wait_for(state="hidden", timeout=30000)
            session.wait_loaded(prior.name)
            require(sha(prior) == previous_sha, "Cancelled opening wrote prior source")
            self.unchanged(protected, checksum)
            marker = f" AFTER-PASSWORD-CANCEL-{source_format} "
            self.edit(session.page, marker)
            session.save(prior, prior)
            text = self.inspect_hwpx(prior)["text"]
            require(self.prior_text in text and text.count(marker) == 1 and self.expected_text not in text,
                    "Prior document failed edit/save after password cancellation")
            self.unchanged(protected, checksum)
            return {"retryMessage": retry_message,
                    "priorSourceSha256Before": previous_sha, "priorEditableAfterCancel": True,
                    "protectedSourceSha256": checksum, "protectedUnchanged": True}
        finally:
            session.close()

    def acknowledge_block(self, session, start: int):
        from pywinauto import Desktop
        def observed():
            for dialog in session.dialogs[start:]:
                if "암호 문서의 원본 저장" in dialog.get("message", ""):
                    return ("webview", dialog["message"])
            native = Desktop(backend="win32").window(class_name="#32770", process=session.proc.pid)
            if native.exists(timeout=0) and native.is_visible():
                return ("native", None)
            return None
        kind, message = self.until(observed, timeout=25, pump=lambda delay: session.page.wait_for_timeout(delay * 1000))
        if kind == "native":
            message = self.dismiss_error(session.proc.pid)
        require("암호 문서의 원본 저장" in message, "Direct Save was not blocked by password policy")
        return {"kind": kind, "message": message}

    def consent(self, session, output_format: str, accept: bool, folder: Path):
        from pywinauto import Desktop
        bound = self.bind_dialog(Desktop(backend="win32"), session.proc.pid)
        native = bound.wrapper_object()
        accessible = Desktop(backend="uia").window(handle=native.handle)
        require(native.window_text() == "암호 없이 저장", "Unexpected native consent title")
        text = "\n".join(item.window_text() for item in self.snapshot(accessible, control_type="Text") if item.window_text())
        require(f"저장한 {output_format.upper()} 파일에는 암호가 적용되지 않습니다" in text,
                f"Missing chosen-format plaintext consent: {text!r}")
        buttons = [item for item in native.descendants(class_name="Button") if item.is_visible() and item.is_enabled()]
        names = [item.window_text().replace("&", "").strip() for item in buttons]
        allowed = {"암호 없이 저장", "OK", "확인"} if accept else {"취소", "Cancel"}
        selected = [item for item in buttons if item.window_text().replace("&", "").strip() in allowed]
        require(len(selected) == 1, f"Expected one consent action; actual buttons {names}")
        native.capture_as_image().save(folder / ("consent-accept.png" if accept else "consent-cancel.png"))
        native.set_focus()
        selected[0].click_input()
        bound.wait_not("visible", timeout=20)
        return {"text": text, "buttons": names, "accepted": accept}

    def unsaved_choice(self, session, protected: Path, choice: str, folder: Path, stage: str):
        """Read and physically choose the real owned dirty-document TaskDialog."""
        from pywinauto import Desktop
        require(choice in ("저장", "취소"), "Unexpected safety-save choice")
        bound = self.bind_dialog(Desktop(backend="win32"), session.proc.pid)
        native = bound.wrapper_object()
        require(native.window_text() == "저장 확인", "Expected dirty-document confirmation")
        accessible = Desktop(backend="uia").window(handle=native.handle)
        text = "\n".join(item.window_text() for item in self.snapshot(accessible, control_type="Text") if item.window_text())
        require(f"{protected.name}의 변경 내용을 저장할까요?" in text,
                f"Confirmation is not bound to the protected document: {text!r}")
        buttons = [item for item in native.descendants(class_name="Button") if item.is_visible() and item.is_enabled()]
        names = [item.window_text().replace("&", "").strip() for item in buttons]
        selected = [item for item in buttons if item.window_text().replace("&", "").strip() == choice]
        require(len(selected) == 1, f"Expected exact native safety action {choice!r}; actual buttons {names}")
        native.capture_as_image().save(folder / f"{stage}-unsaved.png")
        native.set_focus()
        selected[0].click_input()
        bound.wait_not("visible", timeout=20)
        return {"text": text, "buttons": names, "choice": choice}

    def request_native_close(self, session):
        """Send physical Alt+F4 to the unique visible editor HWND owned by this PID."""
        from pywinauto import Desktop
        windows = [window for window in Desktop(backend="win32").windows(process=session.proc.pid)
                   if window.is_visible() and window.is_enabled() and window.window_text()
                   and window.class_name() != "#32770"]
        require(len(windows) == 1, "Expected one owned native editor window before requesting close")
        native = windows[0]
        require(native.process_id() == session.proc.pid, "Native close window ownership differs")
        observed = {"hwnd": native.handle, "processId": native.process_id(),
                    "title": native.window_text(), "class": native.class_name(), "input": "physical Alt+F4"}
        native.set_focus()
        native.type_keys("%{F4}", set_foreground=True)
        return observed

    def protected_still_dirty(self, session, protected: Path, checksum: str):
        require(session.proc.poll() is None and not session.page.is_closed(), "Safety cancellation closed the editor")
        require(session.page.title().startswith("• ") and protected.name in session.page.title(),
                "Safety cancellation replaced the document or lost dirty state")
        self.unchanged(protected, checksum)

    def plaintext_text(self, path: Path, folder: Path):
        if path.suffix == ".hwpx":
            return self.inspect_hwpx(path)["text"]
        require(path.read_bytes().startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"), "HWP output is not CFB")
        self.oracle_count += 1
        converted = folder / f"independent-output-check-{self.oracle_count}.hwpx"
        proc = subprocess.run([str(self.exe.parent / "Tools/rhwp.exe"), "export-hwpx", str(path), str(converted)],
                              capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=90)
        (folder / f"cli-{self.oracle_count}.log").write_text(proc.stdout + "\n" + proc.stderr, encoding="utf-8")
        require(proc.returncode == 0, "Shipped CLI cannot reopen plaintext HWP without a password")
        return self.inspect_hwpx(converted)["text"]

    def save_plaintext(self, source_format: str, output_format: str):
        folder, prior, protected, checksum, session = self.session(f"save-{source_format}-to-{output_format}", source_format)
        plaintext = folder / f"plaintext.{output_format}"
        try:
            dialog = self.open_protected(session, protected)
            dialog, retry_message = self.wrong_password(session, dialog)
            require(prior.name in session.page.title(), "Wrong password replaced prior document before successful retry")
            dialog.locator("#hwp-password-input").fill(self.password)
            dialog.locator("#hwp-password-input").press("Enter")
            dialog.wait_for(state="hidden", timeout=30000)
            session.wait_loaded(protected.name)
            marker = f" NATIVE-PASSWORD-{source_format}-TO-{output_format} "
            self.edit(session.page, marker)
            require(session.page.title().startswith("• "), "Correctly opened document is not editable")
            start = len(session.dialogs)
            self.menu(session.page, "file:save")
            block = self.acknowledge_block(session, start)
            self.unchanged(protected, checksum)
            require(session.page.title().startswith("• "), "Blocked save lost dirty state")
            self.menu(session.page, "file:save-as")
            session.native_dialog(plaintext)
            cancelled = self.consent(session, output_format, False, folder)
            require(not plaintext.exists(), "Cancelled consent created plaintext output")
            self.unchanged(protected, checksum)
            require(session.page.title().startswith("• ") and protected.name in session.page.title(),
                    "Cancelled consent replaced the current document or lost edits")
            self.menu(session.page, "file:save-as")
            session.native_dialog(plaintext)
            accepted = self.consent(session, output_format, True, folder)
            self.until(plaintext.is_file, timeout=30, pump=lambda delay: session.page.wait_for_timeout(delay * 1000))
            session.page.wait_for_function("!document.title.startsWith('• ')", timeout=30000)
            require(plaintext.name in session.page.title(), "Save As did not adopt the plaintext path")
            text = self.plaintext_text(plaintext, folder)
            require(self.expected_text in text and text.count(marker) == 1 and self.prior_text not in text,
                    "Plaintext output does not contain the decrypted document and exactly one edit")
            self.unchanged(protected, checksum)
            session.close()
            session = None
            session = self.Session("native", folder / "fresh-reopen", plaintext, executable=self.exe)
            require(session.page.locator("#hwp-password-input").count() == 0, "Plaintext fresh reopen prompts for a password")
            post = " AFTER-PLAINTEXT-REOPEN "
            self.edit(session.page, post)
            session.save(plaintext, plaintext)
            reopened_text = self.plaintext_text(plaintext, folder)
            require(self.expected_text in reopened_text and reopened_text.count(marker) == 1
                    and reopened_text.count(post) == 1 and self.prior_text not in reopened_text,
                    "Reopened plaintext direct save lost document content or edits")
            self.unchanged(protected, checksum)
            return {"successfulRetryAfterWrongPassword": True, "retryMessage": retry_message,
                    "directSaveBlock": block, "cancelledConsent": cancelled, "acceptedConsent": accepted,
                    "protectedSourceSha256": checksum, "protectedUnchanged": True,
                    "plaintextOutputSha256": sha(plaintext), "freshReopenWithoutPassword": True,
                    "plaintextDirectSaveAfterReopen": True}
        finally:
            if session is not None:
                session.close()

    def dirty_close_replacement(self, source_format: str):
        folder, prior, protected, checksum, session = self.session(f"dirty-close-replacement-{source_format}", source_format)
        cancelled_output = folder / f"cancelled-safety.{source_format}"
        plaintext = folder / f"closed-safety.{source_format}"
        try:
            dialog = self.open_protected(session, protected)
            dialog.locator("#hwp-password-input").fill(self.password)
            dialog.locator("#hwp-password-input").press("Enter")
            dialog.wait_for(state="hidden", timeout=30000)
            session.wait_loaded(protected.name)
            marker = f" DIRTY-SAFETY-{source_format} "
            self.edit(session.page, marker)
            self.protected_still_dirty(session, protected, checksum)

            # Choosing another file must first ask about the dirty protected document.
            self.menu(session.page, "file:open")
            session.native_dialog(prior)
            replacement_cancel = self.unsaved_choice(session, protected, "취소", folder, "replacement-cancel")
            self.protected_still_dirty(session, protected, checksum)
            session.wait_loaded(protected.name)

            close_cancel_input = self.request_native_close(session)
            close_cancel = self.unsaved_choice(session, protected, "취소", folder, "close-cancel")
            self.protected_still_dirty(session, protected, checksum)

            # Safety Save must share the existing operation lock, and cancelled
            # plaintext consent must prevent replacement without losing edits.
            self.menu(session.page, "file:open")
            session.native_dialog(prior)
            replacement_save = self.unsaved_choice(session, protected, "저장", folder, "replacement-save")
            session.native_dialog(cancelled_output)
            replacement_consent = self.consent(session, source_format, False, folder)
            require(not cancelled_output.exists(), "Cancelled safety consent produced a plaintext file")
            self.protected_still_dirty(session, protected, checksum)
            session.wait_loaded(protected.name)
            post = " AFTER-SAFETY-CANCELLATIONS "
            self.edit(session.page, post)

            # Approving safety Save on a real close request must finish the
            # plaintext commit before the app's last native window exits normally.
            close_save_input = self.request_native_close(session)
            close_save = self.unsaved_choice(session, protected, "저장", folder, "close-save")
            session.native_dialog(plaintext)
            close_consent = self.consent(session, source_format, True, folder)
            self.until(lambda: session.proc.poll() is not None, timeout=45)
            require(session.proc.returncode == 0, f"Native close was not a clean process exit: {session.proc.returncode}")
            normal_exit_code = session.proc.returncode
            require(plaintext.is_file(), "Native safety close exited without the approved plaintext output")
            self.unchanged(protected, checksum)
            text = self.plaintext_text(plaintext, folder)
            require(self.expected_text in text and text.count(marker) == 1 and text.count(post) == 1
                    and self.prior_text not in text, "Safety close lost protected-document content or cancelled edits")

            # Session.close now only cleans evidence from an already-exited PID;
            # its taskkill fallback is never accepted as the normal-close proof.
            session.close()
            session = None
            session = self.Session("native", folder / "fresh-safety-reopen", plaintext, executable=self.exe)
            require(session.page.locator("#hwp-password-input").count() == 0, "Safety plaintext reopen prompts for a password")
            reopened = " AFTER-SAFETY-REOPEN "
            self.edit(session.page, reopened)
            session.save(plaintext, plaintext)
            final_text = self.plaintext_text(plaintext, folder)
            require(self.expected_text in final_text and final_text.count(marker) == 1
                    and final_text.count(post) == 1 and final_text.count(reopened) == 1
                    and self.prior_text not in final_text, "Reopened safety output lost content or cannot save edits")
            self.unchanged(protected, checksum)
            return {"replacementCancel": replacement_cancel,
                    "closeCancel": {"nativeInput": close_cancel_input, "confirmation": close_cancel},
                    "replacementSave": replacement_save, "replacementPlaintextConsentCancelled": replacement_consent,
                    "cancelledOutputAbsent": True,
                    "closeSave": {"nativeInput": close_save_input, "confirmation": close_save},
                    "closePlaintextConsentAccepted": close_consent, "normalNativeExitCode": normal_exit_code,
                    "protectedSourceSha256": checksum, "protectedUnchanged": True,
                    "plaintextOutputSha256": sha(plaintext), "freshReopenWithoutPassword": True,
                    "plaintextDirectSaveAfterReopen": True}
        finally:
            if session is not None:
                session.close()

    def run(self):
        cases = [(f"retry-cancel-{fmt}", lambda fmt=fmt: self.retry_cancel(fmt)) for fmt in ("hwp", "hwpx")]
        cases += [(f"save-{src}-to-{dst}", lambda src=src, dst=dst: self.save_plaintext(src, dst))
                  for src in ("hwp", "hwpx") for dst in ("hwp", "hwpx")]
        cases += [(f"dirty-close-replacement-{fmt}", lambda fmt=fmt: self.dirty_close_replacement(fmt))
                  for fmt in ("hwp", "hwpx")]
        for name, action in cases:
            started = time.monotonic()
            record = {"test": name}
            try:
                evidence = action()
                for path, checksum in self.sources.values():
                    self.unchanged(path, checksum)
                require(sha(self.prior) == self.manifest["prior"]["sha256"], "Original prior fixture changed")
                record.update(status="passed", evidence=evidence, fixtureSourcesUnchanged=True)
            except Exception:
                record.update(status="failed", message=traceback.format_exc())
            record["seconds"] = round(time.monotonic() - started, 3)
            self.records.append(record)
            print(f"{name}: {record['status']}", flush=True)
        success = len(self.records) == 8 and all(row["status"] == "passed" for row in self.records)
        result = {**self.identity, "mode": "native-password", "expectedTests": 8, "tests": self.records, "success": success}
        (self.output / "results.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        suite = ET.Element("testsuite", name="OpenGeul native password", tests="8",
                           failures=str(sum(row["status"] != "passed" for row in self.records)), errors="0", skipped="0")
        for row in self.records:
            case = ET.SubElement(suite, "testcase", name=row["test"], time=str(row["seconds"]))
            if row["status"] != "passed":
                ET.SubElement(case, "failure").text = row["message"]
        ET.ElementTree(suite).write(self.output / "junit.xml", encoding="utf-8", xml_declaration=True)
        return 0 if success else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--fixtures", type=Path, required=True)
    parser.add_argument("--exe", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expected-source", default=EXPECTED_SOURCE)
    parser.add_argument("--expected-run", default=EXPECTED_RUN)
    args = parser.parse_args()
    return Qualification(args).run()


if __name__ == "__main__":
    raise SystemExit(main())
