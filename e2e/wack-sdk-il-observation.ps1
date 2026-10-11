param([string]$OutputDirectory, [switch]$SelfTest)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
# Diagnostic only: ildasm reads metadata/IL; no SDK test assembly is loaded or invoked.
$observer = @'
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import threading
import time
import xml.etree.ElementTree as ET

EXPECTED_CARRIER = "61bae06c0dcfa220fff9f771060133bd74c27a2921000a5889e78d24d2eb3679"
STDOUT_LIMIT = 16 * 1024 * 1024
STDERR_LIMIT = 1024 * 1024
JSON_LIMIT = 256 * 1024
CONFIG_LIMIT = 16 * 1024
CLASS_LIMIT = 96 * 1024
METHOD_LIMIT = 64 * 1024
TERMS = ("DPIAwarenessValidation", "DpiAware", "Failed to process the binary")

def file_identity(path):
    if path.is_symlink() or not path.is_file():
        raise ValueError("Expected a regular installed SDK file")
    info = path.stat()
    if info.st_size > 16 * 1024 * 1024:
        raise ValueError("SDK identity file exceeds the hash budget")
    return {"name": path.name, "bytes": info.st_size,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}

def clip(text, budget):
    data = text.encode("utf-8")
    return data[:budget].decode("utf-8", errors="ignore"), len(data) > budget

def extract_il(text):
    # Braces inside strings, token comments and end-of-class comments do not delimit IL blocks.
    masked = re.sub(r'"(?:\\.|[^"\\])*"|//[^\r\n]*|/\*[\s\S]*?\*/',
                    lambda m: " " * len(m.group()), text)
    stack, ends = [], {}
    for m in re.finditer(r"[{}]", masked):
        if m.group() == "{":
            stack.append(m.start())
        elif stack:
            ends[stack.pop()] = m.end()
    starts = list(re.finditer(r"(?m)^[ \t]*\.class\b", masked))
    classes = []
    for m in starts:
        opening = masked.find("{", m.end())
        if opening in ends:
            classes.append((m.start(), ends[opening], text[m.start():opening]))
    all_methods = []
    for m in re.finditer(r"(?ms)^[ \t]*\.method\b.*?^[ \t]*\}[^\r\n]*// end of method[^\r\n]*", text):
        owners = [(a, b, h) for a, b, h in classes if a <= m.start() < b]
        owner = min(owners, key=lambda x: x[1] - x[0]) if owners else (0, 0, "")
        header = m.group().split("{", 1)[0]
        tokens = re.findall(r"(?:/\*\s*|Token:\s*0x)(06[0-9a-fA-F]{6})\b", header)
        all_methods.append({"start": m.start(), "text": m.group(), "classHeader": owner[2],
                            "token": tokens[0].lower() if len(tokens) == 1 else None})
    definitions = {m["token"]: m for m in all_methods if m["token"]}
    def calls(block):
        lines = block.splitlines()
        for i, line in enumerate(lines):
            if re.search(r"\b(?:call|callvirt|newobj)\b", line):
                following = []
                for continuation in lines[i + 1:i + 8]:
                    if re.match(r"\s*(?:IL_[0-9a-f]+:|[{}]|\.(?:try|method))", continuation, re.I):
                        break
                    following.append(continuation)
                statement = "\n".join([line] + following)
                tokens = re.findall(r"(?:/\*\s*|Token:\s*0x)((?:06|0[aA])[0-9a-fA-F]{6})\b", statement)
                yield statement, [token.lower() for token in tokens]
    chosen, methods = [], []
    class_budget, method_budget = CLASS_LIMIT, METHOD_LIMIT
    target_classes, candidates, class_truncated, method_truncated = 0, 0, False, False
    target_ranges = []
    for start, end, header in classes:
        block = text[start:end]
        if "DPIAwarenessValidation" in header:
            target_ranges.append((start, end))
            target_classes += 1
            excerpt, truncated = clip(block, class_budget)
            if excerpt:
                chosen.append({"header": header[:1024], "text": excerpt,
                               "sourceBytes": len(block.encode("utf-8")), "truncated": truncated})
                class_budget -= len(excerpt.encode("utf-8"))
            class_truncated |= truncated
    selected = {m["start"]: m for m in all_methods
                if not any(a <= m["start"] < b for a, b in target_ranges)
                and any(term in m["text"] for term in TERMS)}
    frontier = [m for m in all_methods if any(a <= m["start"] < b for a, b in target_ranges)]
    unresolved, unresolved_count = [], 0
    seen_tokens = set()
    for hop in range(2):
        next_frontier = []
        for source in frontier:
            for statement, tokens in calls(source["text"]):
                for token in tokens or [None]:
                    if token in definitions:
                        if token not in seen_tokens:
                            seen_tokens.add(token)
                            target = definitions[token]
                            if not any(a <= target["start"] < b for a, b in target_ranges):
                                selected[target["start"]] = target
                                next_frontier.append(target)
                    else:
                        unresolved_count += 1
                        if len(unresolved) < 64:
                            unresolved.append({"token": token, "statement": statement[:768],
                                               "reason": "no-resolvable-local-MethodDef-token", "hop": hop + 1})
        frontier = next_frontier
    for item in sorted(selected.values(), key=lambda m: m["start"]):
        method = item["text"]
        candidates += 1
        excerpt, truncated = clip(method, method_budget)
        if excerpt and len(methods) < 24:
            methods.append({"classHeader": item["classHeader"][:1024], "token": item["token"],
                            "text": excerpt, "sourceBytes": len(method.encode("utf-8")), "truncated": truncated})
            method_budget -= len(excerpt.encode("utf-8"))
        else:
            truncated = True
        method_truncated |= truncated
    references, total_references = [], 0
    for entry in chosen + methods:
        lines = entry["text"].splitlines()
        for i, line in enumerate(lines):
            if re.search(r"\b(?:call|callvirt|newobj|catch|pinvokeimpl)\b", line):
                total_references += 1
                if len(references) < 96:
                    references.append("\n".join(lines[max(0, i - 1):i + 4])[:768])
    prefix_end = starts[0].start() if starts else len(text)
    assembly_refs = re.findall(r"(?ms)^\.assembly extern\b.*?^\}", text[:prefix_end])
    prefix, prefix_truncated = clip("\n".join(assembly_refs), 8192)
    return {"targetClassCount": target_classes, "targetClasses": chosen,
            "targetClassesTruncated": class_truncated,
            "neighborMethodCandidates": candidates, "neighborMethods": methods,
            "neighborMethodsTruncated": method_truncated,
            "callsAndExceptionClauses": references, "referenceCountInKeptText": total_references,
            "referencesTruncated": total_references > len(references),
            "localHelperResolutionHops": 2, "localMethodDefinitionsWithTokens": len(definitions),
            "unresolvedCallTargets": unresolved, "unresolvedCallTargetCount": unresolved_count,
            "unresolvedCallTargetsTruncated": unresolved_count > len(unresolved),
            "assemblyReferences": prefix, "assemblyReferencesTruncated": prefix_truncated}

def config_observation(path):
    if path.stat().st_size > 1024 * 1024:
        raise ValueError("SDK configuration exceeds the input budget")
    raw = path.read_bytes()
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        text = raw.decode("utf-16")
    else:
        text = raw.decode("utf-8-sig")
    positions = [m.start() for m in re.finditer("DPIAwarenessValidation", text)]
    windows = [(max(0, p - 1400), min(len(text), p + 1800)) for p in positions]
    merged = []
    for start, end in windows:
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    contexts = [{"startCharacter": a, "endCharacter": b, "text": text[a:b]}
                for a, b in merged[:8]]
    root = ET.fromstring(raw)
    parents = {child: parent for parent in root.iter() for child in parent}
    mappings = []
    for element in root.iter():
        if any("DPIAwarenessValidation" in value for value in element.attrib.values()):
            parent = parents.get(element)
            grandparent = parents.get(parent)
            mappings.append({"tag": element.tag, "attributes": element.attrib,
                             "parentTag": parent.tag if parent is not None else None,
                             "parentAttributes": parent.attrib if parent is not None else None,
                             "grandparentTag": grandparent.tag if grandparent is not None else None,
                             "grandparentAttributes": grandparent.attrib if grandparent is not None else None})
    result = {"identity": file_identity(path), "literalMatches": len(positions),
              "contexts": contexts, "mappings": mappings[:16],
              "truncated": len(merged) > 8 or len(mappings) > 16}
    while len(json.dumps(result, ensure_ascii=True).encode("ascii")) > CONFIG_LIMIT:
        result["truncated"] = True
        if result["contexts"]:
            last = result["contexts"][-1]
            if len(last["text"]) > 256:
                last["text"] = last["text"][:len(last["text"]) // 2]
                last["endCharacter"] = last["startCharacter"] + len(last["text"])
            else:
                result["contexts"].pop()
        elif result["mappings"]:
            result["mappings"].pop()
        else:
            raise ValueError("SDK configuration metadata exceeds the output budget")
    return result

def capture(command):
    began = time.monotonic()
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    overflow = threading.Event()
    streams = [{"kept": bytearray(), "observed": 0, "limit": limit, "truncated": False}
               for limit in (STDOUT_LIMIT, STDERR_LIMIT)]
    def read_stream(source, record):
        with source:
            while True:
                chunk = source.read(65536)
                if not chunk:
                    break
                record["observed"] += len(chunk)
                remaining = record["limit"] - len(record["kept"])
                record["kept"].extend(chunk[:remaining])
                if len(chunk) > remaining:
                    record["truncated"] = True
                    overflow.set()
    readers = [threading.Thread(target=read_stream, args=(source, record), daemon=True)
               for source, record in zip((process.stdout, process.stderr), streams)]
    for reader in readers:
        reader.start()
    timed_out = False
    while process.poll() is None:
        if overflow.is_set() or time.monotonic() - began >= 30:
            timed_out = time.monotonic() - began >= 30
            process.kill()
            break
        overflow.wait(0.02)
    process.wait(timeout=5)
    for reader in readers:
        reader.join(timeout=2)
    stdout, stderr = streams
    return {"exitCode": process.returncode, "elapsedSeconds": round(time.monotonic() - began, 3),
            "timedOut": timed_out, "stdoutBytesObserved": stdout["observed"],
            "stdoutBytesKept": len(stdout["kept"]), "stdoutTruncated": stdout["truncated"],
            "stderrBytesObserved": stderr["observed"], "stderrBytesKept": len(stderr["kept"]),
            "stderrTruncated": stderr["truncated"], "readerThreadsFinished": not any(t.is_alive() for t in readers)}, bytes(stdout["kept"]), bytes(stderr["kept"])

def encode_result(result):
    result.setdefault("jsonBudgetTruncated", False)
    while True:
        encoded = json.dumps(result, ensure_ascii=True, separators=(",", ":")).encode("ascii")
        if len(encoded) <= JSON_LIMIT:
            return encoded
        result["jsonBudgetTruncated"] = True
        il = result["il"]
        if il["callsAndExceptionClauses"]:
            il["callsAndExceptionClauses"].pop()
            il["referencesTruncated"] = True
        elif il["unresolvedCallTargets"]:
            il["unresolvedCallTargets"].pop()
            il["unresolvedCallTargetsTruncated"] = True
        elif il["neighborMethods"]:
            il["neighborMethods"].pop()
            il["neighborMethodsTruncated"] = True
        elif il["targetClasses"]:
            entry = il["targetClasses"][-1]
            entry["text"] = entry["text"][:len(entry["text"]) // 2]
            entry["truncated"] = il["targetClassesTruncated"] = True
            if not entry["text"]:
                il["targetClasses"].pop()
        else:
            raise ValueError("Observation metadata exceeds its output budget")

def decode_observation(data):
    import os
    metadata = {"childInheritsConsole": True, "consoleOutputCodePage": None, "ansiCodePage": None}
    encoding = "utf-8-sig"
    if os.name == "nt":
        import ctypes
        console = ctypes.windll.kernel32.GetConsoleOutputCP()
        ansi = ctypes.windll.kernel32.GetACP()
        metadata.update(consoleOutputCodePage=console, ansiCodePage=ansi)
        encoding = "utf-8-sig" if data.startswith(b"\xef\xbb\xbf") else "cp" + str(console or ansi)
    metadata["decodeEncoding"] = encoding
    return data.decode(encoding, errors="replace"), metadata

def self_test():
    import tempfile
    sample = '''.assembly extern NativeAnalyzer
{
}
.class public Tests.DPIAwarenessValidation
{
 .class nested private Worker
 {
  .method public Nested() cil managed
  {
   IL_0000: ldstr "string containing { braces }"
  } // end of method Worker::Nested
 } // end of class Tests.DPIAwarenessValidation/Worker
 .method public Check() cil managed
 {
  IL_0000: call /*06000002*/ bool Helpers::Inspect(string)
  IL_0001: call /*0A000003*/ bool [NativeAnalyzer]BinaryInfo::Check(string)
  catch [mscorlib]System.Exception
  {
   IL_0010: call string Resources::get_DpiAwareFailedToProcessBinary()
  }
 } // end of method DPIAwarenessValidation::Check
} // end of class Tests.DPIAwarenessValidation
.class private Helpers
{
 .method /*06000002*/ public Inspect(string) cil managed
 {
  IL_0000: call /*06000004*/ void Helpers::Next()
 } // end of method Helpers::Inspect
 .method /*06000004*/ public Next() cil managed
 {
  IL_0000: ret
 } // end of method Helpers::Next
}
.class private Resources
{
 .method public get_DpiAwareFailedToProcessBinary() cil managed
 {
  IL_0000: ldstr "Failed to process the binary {0}."
 } // end of method Resources::get_DpiAwareFailedToProcessBinary
 .method public Unrelated() cil managed
 {
  IL_0000: ldstr "unrelated"
 } // end of method Resources::Unrelated
}
'''
    result = extract_il(sample)
    assert result["targetClassCount"] == 1 and result["neighborMethodCandidates"] == 3
    assert "catch [mscorlib]System.Exception" in result["targetClasses"][0]["text"]
    assert "BinaryInfo::Check" in "\n".join(result["callsAndExceptionClauses"])
    assert not result["targetClassesTruncated"] and "Nested" in result["targetClasses"][0]["text"]
    assert any("Helpers::Inspect" in item["text"] for item in result["neighborMethods"])
    assert any("Helpers::Next" in item["text"] for item in result["neighborMethods"])
    assert all("Unrelated" not in item["text"] for item in result["neighborMethods"])
    assert any(item["token"] == "0a000003" for item in result["unresolvedCallTargets"])
    large = sample.replace("IL_0000: call", "x" * (CLASS_LIMIT + 1024) + "\n  IL_0000: call", 1)
    assert extract_il(large)["targetClassesTruncated"]
    assert extract_il(".class unrelated\n{\n}")["targetClassCount"] == 0
    with tempfile.TemporaryDirectory() as temporary:
        config = Path(temporary) / "configuration.xml"
        config.write_bytes(('<Configuration><Tests><Test Name="DPIAwarenessValidation" '
                            'Assembly="microsoft.windows.softwarelogo.tests.dll" />'
                            '</Tests></Configuration>').encode("utf-16"))
        observation = config_observation(config)
        assert observation["mappings"][0]["attributes"]["Assembly"] == "microsoft.windows.softwarelogo.tests.dll"
        assert observation["mappings"][0]["parentTag"] == "Tests" and not observation["truncated"]
    capture_result, stdout, stderr = capture([sys.executable, "-c", "print('metadata only')"])
    assert capture_result["exitCode"] == 0 and b"metadata only" in stdout and not stderr
    oversized = {"il": extract_il(sample), "extra": "x" * (JSON_LIMIT - 4096)}
    oversized["il"]["targetClasses"][0]["text"] = "x" * CLASS_LIMIT
    encoded = encode_result(oversized)
    assert len(encoded) <= JSON_LIMIT and json.loads(encoded)["jsonBudgetTruncated"]
    print("WACK SDK IL extractor self-test passed")

if __name__ == "__main__":
    if sys.argv[1:] == ["--self-test"]:
        self_test()
    else:
        kit, ildasm, output = map(Path, sys.argv[1:])
        carrier = kit / "microsoft.windows.softwarelogo.tests.dll"
        stage = "carrier-identity"
        try:
            if carrier.stat().st_size > 1024 * 1024:
                raise ValueError("carrier-size")
            identity = file_identity(carrier)
            if identity["sha256"] != EXPECTED_CARRIER:
                raise ValueError("carrier-sha256-mismatch")
            stage = "tool-identity"
            tool_identity = file_identity(ildasm)
            stage = "ildasm-capture"
            command = [str(ildasm), "/text", "/nobar", "/utf8", "/tokens", "/raweh", str(carrier)]
            details, stdout, stderr = capture(command)
            stage = "decode-and-extraction"
            text, encoding = decode_observation(stdout)
            stderr_text, _ = decode_observation(stderr)
            stderr_text, stderr_excerpt_truncated = clip(stderr_text, 4096)
            result = {"scope": "diagnostic-only static IL/metadata and configuration observation; no SDK test DLL execution",
                      "carrier": identity, "tool": tool_identity, "arguments": command[1:-1],
                      "capture": details, "encoding": encoding, "stdoutDecodeReplacements": text.count("\ufffd"),
                      "stderrExcerpt": stderr_text, "stderrExcerptTruncated": stderr_excerpt_truncated,
                      "il": extract_il(text), "configuration": config_observation(kit / "configuration.xml")}
            result["captureComplete"] = (details["exitCode"] == 0 and not details["timedOut"]
                                          and not details["stdoutTruncated"] and not details["stderrTruncated"]
                                          and details["readerThreadsFinished"])
            result["excerptsComplete"] = (result["il"]["targetClassCount"] > 0
                                           and not result["stdoutDecodeReplacements"]
                                           and result["configuration"]["literalMatches"] > 0
                                           and bool(result["configuration"]["mappings"])
                                           and not result["configuration"]["truncated"]
                                           and not any(v for k, v in result["il"].items() if k.endswith("Truncated")))
            result["complete"] = result["captureComplete"] and result["excerptsComplete"]
            encoded = encode_result(result)
            if result["jsonBudgetTruncated"]:
                result["complete"] = result["excerptsComplete"] = False
                encoded = encode_result(result)
            with output.open("xb") as target:
                target.write(encoded)
            print("Bounded WACK SDK IL observation written; complete=" + str(result["complete"]))
        except Exception as error:
            reason = str(error) if str(error) in ("carrier-size", "carrier-sha256-mismatch") else "probe-error"
            failure = {"scope": "diagnostic-only static SDK observation", "complete": False,
                       "failureStage": stage, "errorType": type(error).__name__, "reasonCode": reason}
            if not output.exists():
                output.write_text(json.dumps(failure, separators=(",", ":")), encoding="utf-8")
            print("SDK IL observation failed: " + stage + ": " + reason)
            sys.exit(1)
'@
if ($SelfTest) {
    $observer | python - --self-test
    if ($LASTEXITCODE -ne 0) { throw 'SDK IL extractor self-test failed.' }
    return
}
if (-not $OutputDirectory) { throw 'OutputDirectory is required.' }
New-Item -ItemType Directory -Force -Path $OutputDirectory | Out-Null
$observationPath = Join-Path $OutputDirectory 'wack-sdk-il-observation.json'
$stage = 'installed-tool-search'
try {
if ($env:GITHUB_ACTIONS -ne 'true') { throw 'SDK IL diagnostics are restricted to disposable GitHub Actions runners.' }
$kit = [System.IO.Path]::GetFullPath((Join-Path ${env:ProgramFiles(x86)} 'Windows Kits/10/App Certification Kit'))
$roots = @((Join-Path ${env:ProgramFiles(x86)} 'Microsoft SDKs/Windows'), (Join-Path ${env:ProgramFiles(x86)} 'Windows Kits/NETFXSDK'))
$directories = [System.Collections.Generic.Stack[System.IO.DirectoryInfo]]::new()
foreach ($path in $roots) {
    if (Test-Path -LiteralPath $path -PathType Container) { $directories.Push((Get-Item -LiteralPath $path)) }
}
$candidates = [System.Collections.Generic.List[System.IO.FileInfo]]::new()
$entries = 0; $folders = 0
while ($directories.Count -gt 0) {
    $directory = $directories.Pop()
    $folders++
    if ($folders -gt 512) { throw 'Installed ildasm search exceeded the folder budget.' }
    if ($directory.Attributes -band [System.IO.FileAttributes]::ReparsePoint) { continue }
    foreach ($entry in $directory.EnumerateFileSystemInfos()) {
        $entries++
        if ($entries -gt 4096) { throw 'Installed ildasm search exceeded the entry budget.' }
        if ($entry.Attributes -band [System.IO.FileAttributes]::ReparsePoint) { continue }
        if ($entry -is [System.IO.DirectoryInfo]) { $directories.Push($entry) }
        elseif ($entry -is [System.IO.FileInfo] -and $entry.Name -ieq 'ildasm.exe') {
            $candidates.Add($entry)
            if ($candidates.Count -gt 16) { throw 'Installed ildasm search exceeded the candidate budget.' }
        }
    }
}
$ildasm = $candidates | Sort-Object @{Expression={ $_.Directory.Name -eq 'x64' };Descending=$true}, @{Expression={ $_.FullName };Descending=$true} | Select-Object -First 1
if (-not $ildasm) { throw 'Installed NETFX SDK ildasm.exe was not found; no tool is downloaded.' }
$stage = 'static-il-observation'
$observer | python - $kit $ildasm.FullName $observationPath
if ($LASTEXITCODE -ne 0) { throw 'SDK IL observation failed.' }
} catch {
    if (-not (Test-Path -LiteralPath $observationPath)) {
        @{scope='diagnostic-only static SDK observation';complete=$false;failureStage=$stage;
          errorType=$_.Exception.GetBaseException().GetType().Name;reasonCode='powershell-probe-error'} |
          ConvertTo-Json -Compress | Set-Content -LiteralPath $observationPath -Encoding utf8
    }
    throw
}
