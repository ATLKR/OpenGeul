"""Fetch frozen failed-source package and WASM for password diagnostics only."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "e2e"))
import windows_components as components
from prepare_payload import inventory, stream_hash, verify_checksums, prepare as prepare_runtime
from releasekit import verify_msix
import wasm_artifacts

REPOSITORY = "ATLKR/OpenGeul"
SOURCE = "9b666ea2ac3210a6219ca9d78b9da96719b43856"
RUN_ID = 38161639847
ATTEMPT = 1
PACKAGE_NAME = "OpenGeul_1.1.2.0_x64_development-unsigned.msix"
PORTABLE_NAME = "OpenGeul_1.1.2_windows-x64_unsigned-portable.zip"
PACKAGE_FILES = {PACKAGE_NAME, PORTABLE_NAME, "AppxManifest.xml", "rhwp-help.txt", "provenance.json", "SHA256SUMS.txt"}
RUNTIMES = {
    "editor": {"path": "OpenGeul.exe", "size": 33641472,
               "sha256": "6087e550b367adafecd03a08e72132390250da4e31283e4008bd88048e7ab6db"},
    "cli": {"path": "Tools/rhwp.exe", "size": 36530176,
            "sha256": "63009e615309e81bcfef84e97e61f01bb2a59ad39a672ffacf94457934eeaed5"},
}
SOURCE_CONTRACT_SHA256 = "a407bd53deb16cd7e50507ece47fe7dc0f2c24294a52c7c182c365cbe49da1a8"
LEDGER_CANONICAL_SHA256 = "fe8022be2db8d454e0ff8a0f536abd0552b780d25ba5df3cf5f5421852456af0"
COMPONENT_PROVENANCE = {
    "editor": "dc8dc1da79a9106e88856b3ac7694c703504ed9037790bbfafab1f1b4f3b13d8",
    "cli": "6901b40b3c8a8ecc7f337e8134e8bf099e55d6a002309acb09b5d7ef53b018df",
}
ARTIFACTS = {
    "package": {"id": 11711628175, "name": "opengeul-windows-x64-38161639847", "size": 59518775,
                "sha256": "024cf1049a42606a0d6081761e5909c21bbf1e2cadee4af607f01d8550ff2c10",
                "archiveLimit": 64 * 1024 * 1024, "expandedLimit": 128 * 1024 * 1024},
    "wasm": {"id": 11710548366, "name": "opengeul-wasm-38161639847", "size": 4829693,
             "sha256": "fcd64a8ecd840bb86d28960e6314eee55a8e553f0172d8ec09a39ad681746c1a",
             "archiveLimit": 32 * 1024 * 1024, "expandedLimit": 33 * 1024 * 1024},
}
IDENTITY = {"repository": REPOSITORY, "commit": SOURCE, "runId": str(RUN_ID), "runAttempt": str(ATTEMPT)}
PRODUCER_JOBS = {"wasm": 114535716813, "build": 114545338430}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def gh_json(endpoint):
    result = subprocess.run(["gh", "api", endpoint], stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, timeout=60)
    require(result.returncode == 0, "GitHub metadata request failed")
    require(len(result.stdout) <= 2 * 1024 * 1024, "GitHub metadata exceeds limit")
    try:
        return json.loads(result.stdout)
    except (ValueError, UnicodeError):
        raise ValueError("GitHub metadata is invalid") from None


def pages(endpoint, key):
    records = []
    for page in range(1, 11):
        value = gh_json(f"{endpoint}?per_page=100&page={page}")
        batch = value.get(key)
        require(isinstance(batch, list) and len(batch) <= 100, "GitHub collection is invalid")
        records.extend(batch)
        require(type(value.get("total_count")) is int and 0 <= value["total_count"] <= 1000,
                "GitHub collection exceeds limit")
        if len(records) >= value["total_count"]:
            require(len(records) == value["total_count"], "GitHub collection changed during read")
            return records
        require(bool(batch), "GitHub collection is incomplete")
    raise ValueError("GitHub collection exceeds limit")


def validate_run(run, jobs):
    require(isinstance(run, dict) and run.get("id") == RUN_ID and run.get("head_sha") == SOURCE
            and run.get("run_attempt") == ATTEMPT and run.get("run_number") == 61
            and run.get("event") == "push" and run.get("head_branch") == "main"
            and run.get("path") == ".github/workflows/msix.yml"
            and run.get("status") == "completed" and run.get("conclusion") == "failure",
            "Producer run identity or terminal outcome differs")
    repository = run.get("repository", {})
    require(repository.get("full_name") == REPOSITORY and repository.get("private") is False
            and type(repository.get("id")) is int, "Producer repository identity differs")
    head_repository = run.get("head_repository", {})
    require(head_repository.get("full_name") == REPOSITORY and head_repository.get("private") is False
            and head_repository.get("id") == repository["id"], "Producer head repository identity differs")
    selected = {}
    for name, job_id in PRODUCER_JOBS.items():
        matches = [job for job in jobs if job.get("name") == name]
        require(len(matches) == 1, "Producer job is missing or ambiguous")
        job = matches[0]
        require(job.get("run_id") == RUN_ID and job.get("status") == "completed"
                and job.get("conclusion") == "success" and job.get("id") == job_id
                and type(job.get("run_attempt")) is int and job.get("run_attempt") == ATTEMPT
                and job.get("head_sha") == SOURCE,
                "Required producer job did not succeed")
        selected[name] = {"id": job["id"], "conclusion": "success"}
    return selected


def validate_artifact(value, spec, repository_id):
    require(isinstance(value, dict) and value.get("id") == spec["id"] and value.get("name") == spec["name"]
            and value.get("size_in_bytes") == spec["size"]
            and value.get("digest") == "sha256:" + spec["sha256"] and value.get("expired") is False,
            "Pinned artifact identity, size or digest differs")
    origin = value.get("workflow_run", {})
    require(origin.get("id") == RUN_ID and origin.get("head_sha") == SOURCE
            and origin.get("head_branch") == "main" and origin.get("repository_id") == repository_id
            and origin.get("head_repository_id") == repository_id,
            "Artifact producer binding differs")
    try:
        expires = datetime.fromisoformat(value["expires_at"].replace("Z", "+00:00"))
        require(expires.tzinfo is not None and expires > datetime.now(timezone.utc), "Pinned artifact has expired")
    except (KeyError, TypeError, AttributeError, ValueError):
        raise ValueError("Pinned artifact expiration is invalid or expired") from None


def download_archive(spec, path):
    components.fresh(path)
    with path.open("xb") as output:
        result = subprocess.run(["gh", "api", f"repos/{REPOSITORY}/actions/artifacts/{spec['id']}/zip"],
                                stdout=output, stderr=subprocess.PIPE, timeout=180)
    require(result.returncode == 0, "GitHub artifact download failed")


def extract_verified_archive(path, spec, output):
    components.regular(path)
    require(path.stat().st_size == spec["size"] and spec["size"] <= spec["archiveLimit"],
            "Downloaded artifact size differs")
    with path.open("rb") as stream:
        require(stream_hash(stream) == spec["sha256"], "Downloaded artifact digest differs")
    components.fresh(output)
    with zipfile.ZipFile(path) as archive:
        entries = archive.infolist()
        require(sum(entry.file_size for entry in entries) <= spec["expandedLimit"]
                and all(entry.file_size <= spec["expandedLimit"] and entry.compress_type in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED) for entry in entries),
                "Artifact expansion exceeds limit")
        files = inventory(archive)
        # Validate every directory name too; inventory rejects aliases and special modes.
        for entry in entries:
            components.safe_name(entry.filename.rstrip("/"))
        output.mkdir(parents=True)
        try:
            for name, entry in files.items():
                destination = output.joinpath(*name.split("/"))
                destination.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(entry) as source, destination.open("xb") as target:
                    shutil.copyfileobj(source, target)
        except BaseException:
            shutil.rmtree(output)
            raise


def validate_inputs(package, wasm, runtime):
    verify_checksums(package)
    require({path.name for path in package.iterdir()} == PACKAGE_FILES, "Package file inventory differs")
    provenance = components.read_json(package / "provenance.json")
    require(provenance.get("repository") == REPOSITORY and provenance.get("commit") == SOURCE
            and provenance.get("runId") == str(RUN_ID) and provenance.get("version") == "1.1.2"
            and provenance.get("package") == PACKAGE_NAME, "Package source/run identity differs")
    require(provenance.get("upstream") == components.configured()["upstream"], "Package upstream differs")
    msix = verify_msix(package / PACKAGE_NAME)
    require(msix["sha256"] == provenance.get("sha256"), "Package MSIX digest differs")
    with zipfile.ZipFile(package / PACKAGE_NAME) as archive:
        require(archive.read("AppxManifest.xml") == (package / "AppxManifest.xml").read_bytes(),
                "Package manifest sidecar differs")
    ledger = provenance.get("sourceParity")
    require(isinstance(ledger, dict) and hashlib.sha256(components.encoded(ledger)).hexdigest() == LEDGER_CANONICAL_SHA256,
            "Frozen package source ledger differs")
    expected = {"formatVersion": 1, **IDENTITY, "sourceContractSha256": SOURCE_CONTRACT_SHA256, "components": {}}
    for role, record in RUNTIMES.items():
        expected["components"][role] = {"artifactName": f"opengeul-{role}-component-{RUN_ID}", "runAttempt": str(ATTEMPT),
            "provenanceSha256": COMPONENT_PROVENANCE[role], "runtime": record["path"],
            "size": record["size"], "sha256": record["sha256"]}
    require(provenance.get("windowsComponents") == expected, "Frozen Windows component receipt differs")
    files, directories = components.tree(wasm, ARTIFACTS["wasm"]["expandedLimit"])
    require(not directories and set(files) == set(wasm_artifacts.FILES) | {"OPEN_GEUL_WASM.json"}, "WASM file inventory differs")
    wasm_artifacts.validate(wasm)
    manifest = components.read_json(wasm / "OPEN_GEUL_WASM.json")
    require(manifest == ledger.get("wasmRebuild"), "Package and fixture WASM source parity differs")
    require(set(manifest) == {"upstream", "namespaceHelper", "namespacePatcher", "artifacts", "generator"}
            and manifest["artifacts"] == {name: files[name]["sha256"] for name in wasm_artifacts.FILES}, "WASM file digests differ")
    for key, value in wasm_artifacts.expected().items():
        require(manifest.get(key) == value, "WASM source namespace or upstream differs")
    try:
        prepared = prepare_runtime(package, runtime)
        for role, record in RUNTIMES.items():
            path = runtime / record["path"]
            require(path.stat().st_size == record["size"] and components.sha(path) == record["sha256"],
                    "Pinned package executable differs")
    except BaseException:
        if runtime.exists(): shutil.rmtree(runtime)
        raise
    return {"runtime": RUNTIMES, "verifiedRuntimeFiles": prepared["verifiedRuntimeFiles"],
            "runtimeManifestSha256": prepared["runtimeManifestSha256"], "packageMsixSha256": msix["sha256"],
            "packageProvenanceSha256": components.sha(package / "provenance.json"),
            "sourceContractSha256": SOURCE_CONTRACT_SHA256, "sourceLedgerCanonicalSha256": LEDGER_CANONICAL_SHA256,
            "wasmProvenanceSha256": components.sha(wasm / "OPEN_GEUL_WASM.json"),
            "wasmArtifacts": manifest["artifacts"], "wasmRebuild": manifest}


def prepare(root=ROOT, output=None):
    components._ancestors(Path(root))
    root = Path(root).resolve()
    output = Path(output) if output is not None else root / "evidence/source.json"
    if not output.is_absolute():
        output = root / output
    require(".." not in output.parts and output.is_relative_to(root),
            "Diagnostic receipt must stay inside its checkout")
    package = root / "package"
    runtime = root / "runtime"
    wasm = root / "fixture-hop/apps/studio-host/vendor/rhwp-core"
    for destination in (package, runtime, root / "fixture-hop", output):
        components.fresh(destination)
    run = gh_json(f"repos/{REPOSITORY}/actions/runs/{RUN_ID}")
    jobs = pages(f"repos/{REPOSITORY}/actions/runs/{RUN_ID}/attempts/{ATTEMPT}/jobs", "jobs")
    producer_jobs = validate_run(run, jobs)
    listed = pages(f"repos/{REPOSITORY}/actions/runs/{RUN_ID}/artifacts", "artifacts")
    metadata = {}
    for role, spec in ARTIFACTS.items():
        matches = [value for value in listed if value.get("name") == spec["name"]]
        require(len(matches) == 1, "Same-run pinned artifact is missing or ambiguous")
        validate_artifact(matches[0], spec, run["repository"]["id"])
        fixed = gh_json(f"repos/{REPOSITORY}/actions/artifacts/{spec['id']}")
        validate_artifact(fixed, spec, run["repository"]["id"])
        require(all(fixed.get(key) == matches[0].get(key) for key in
                    ("id", "name", "size_in_bytes", "digest", "expired", "expires_at", "workflow_run")),
                "Fixed artifact and same-run listing differ")
        metadata[role] = {"id": spec["id"], "name": spec["name"], "bytes": spec["size"],
                          "sha256": spec["sha256"], "expiresAt": fixed["expires_at"]}
    root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".password61-", dir=root) as temporary:
        stage = Path(temporary)
        for role, spec in ARTIFACTS.items():
            archive = stage / (role + ".zip")
            download_archive(spec, archive)
            extract_verified_archive(archive, spec, stage / role)
        verified = validate_inputs(stage / "package", stage / "wasm", stage / "runtime")
        value = {"qualification": "native-password-diagnostic-only", "qualifiedPackage": False,
                 "diagnosticOnly": True, "sourceQualified": False, "fullSourceQualified": False, "producerRunNumber": 61,
                 "sourceCommit": SOURCE, "sourceRun": RUN_ID, "producerRunId": str(RUN_ID), "producerAttempt": ATTEMPT,
                 "repository": REPOSITORY, "producerConclusion": run["conclusion"],
                 "producerJobs": producer_jobs, "artifacts": metadata, **verified,
                 "checkedAtUtc": datetime.now(timezone.utc).isoformat()}
        # No verified input reaches its final location until both inputs pass.
        for destination in (package, runtime, root / "fixture-hop", output):
            components.fresh(destination)
        wasm.parent.mkdir(parents=True)
        output.parent.mkdir(parents=True, exist_ok=True)
        (stage / "package").rename(package)
        (stage / "runtime").rename(runtime)
        (stage / "wasm").rename(wasm)
        with output.open("x", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2, sort_keys=True)
            stream.write("\n")
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("evidence/source.json"))
    args = parser.parse_args()
    try:
        prepare(output=args.output)
    except Exception:
        print("Package61 diagnostic input verification failed.", file=sys.stderr)
        return 1
    print("Verified pinned failed-source Package61 and WASM61 diagnostic inputs.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
