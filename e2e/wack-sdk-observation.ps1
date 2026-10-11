param([string]$OutputDirectory, [switch]$SelfTest)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$scanner = @'
import hashlib
import json
import os
from pathlib import Path
import stat
import sys

FILE_LIMIT = 16 * 1024 * 1024
TOTAL_LIMIT = 128 * 1024 * 1024
JSON_LIMIT = 512 * 1024
TERMS = ("Failed to process the binary", "DPIAwarenessValidation", "DpiAware")

def matches(data, remaining):
    hits, truncated = [], False
    for term in TERMS:
        for encoding in ("ascii", "utf-16le"):
            needle = term.encode(encoding)
            offset, kept = data.find(needle), 0
            while offset >= 0:
                if kept == 4 or remaining[term] == 0:
                    truncated = True
                    break
                hits.append({"term": term, "encoding": encoding,
                             "offsetBytes": offset, "snippet": term})
                remaining[term] -= 1
                kept += 1
                offset = data.find(needle, offset + 1)
    return hits, truncated

def encode_result(result):
    encoded = json.dumps(result, ensure_ascii=True, separators=(",", ":")).encode("ascii")
    while len(encoded) > JSON_LIMIT and result["files"]:
        result["files"].pop()
        result["omittedForJsonLimit"] += 1
        result["complete"] = False
        encoded = json.dumps(result, ensure_ascii=True, separators=(",", ":")).encode("ascii")
    if len(encoded) > JSON_LIMIT:
        raise ValueError("JSON budget")
    return encoded

def normal_file(path, root):
    cursor = path
    while True:
        info = cursor.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise ValueError("reparse point")
        if cursor == root:
            break
        cursor = cursor.parent
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode):
        raise ValueError("not a regular file")
    return info

def observe(metadata, kit):
    if len(metadata["files"]) > 512:
        raise ValueError("file budget")
    result = {"scope": "read-only installed App Certification Kit inventory and literal search",
              "complete": not metadata["limitReasons"], "limitReasons": metadata["limitReasons"],
              "reparseEntriesSkipped": metadata["reparseEntriesSkipped"],
              "bytesBudgeted": 0, "matchesTruncated": False, "omittedForJsonLimit": 0, "files": []}
    remaining = dict.fromkeys(TERMS, 128)
    for item in metadata["files"]:
        record = dict(item)
        record.update(sha256=None, matches=[])
        result["files"].append(record)
        if item.get("skipReason"):
            result["complete"] = False
            continue
        try:
            relative = Path(item["path"])
            if relative.is_absolute() or relative.drive or not relative.parts or ".." in relative.parts:
                raise ValueError("relative path")
            if relative.suffix.lower() not in (".exe", ".dll", ".mui", ".xml", ".config"):
                raise ValueError("extension")
            path = kit / relative
            info = normal_file(path, kit)
            size = info.st_size
            if size != item["bytes"] or size > FILE_LIMIT or size > TOTAL_LIMIT - result["bytesBudgeted"]:
                raise ValueError("size or byte budget")
            result["bytesBudgeted"] += size
            with path.open("rb") as source:
                opened = os.fstat(source.fileno())
                if (opened.st_dev, opened.st_ino, opened.st_size) != (info.st_dev, info.st_ino, size):
                    raise ValueError("file changed")
                data = source.read(size)
                after = os.fstat(source.fileno())
            if len(data) != size or (after.st_size, after.st_mtime_ns) != (size, info.st_mtime_ns):
                raise ValueError("file changed")
            record["sha256"] = hashlib.sha256(data).hexdigest()
            record["matches"], truncated = matches(data, remaining)
            result["matchesTruncated"] |= truncated
        except (OSError, ValueError) as error:
            record["readErrorType"] = type(error).__name__
            result["complete"] = False
    return result

def self_test():
    import tempfile
    data = b"\xff" + TERMS[0].encode("ascii") + TERMS[1].encode("utf-16le")
    hits, truncated = matches(data, dict.fromkeys(TERMS, 128))
    assert [(hit["term"], hit["offsetBytes"]) for hit in hits] == [(TERMS[0], 1), (TERMS[1], 29)]
    assert all(hit["snippet"] == hit["term"] for hit in hits) and not truncated
    hits, truncated = matches((TERMS[2] + " ").encode("ascii") * 10, dict.fromkeys(TERMS, 128))
    assert len(hits) == 4 and truncated
    hits, truncated = matches(data, dict.fromkeys(TERMS, 0))
    assert not hits and truncated
    result = {"files": [{"path": "x" * JSON_LIMIT}], "omittedForJsonLimit": 0, "complete": True}
    assert len(encode_result(result)) <= JSON_LIMIT and result["omittedForJsonLimit"] == 1
    try:
        observe({"files": [{}] * 513, "limitReasons": [], "reparseEntriesSkipped": 0}, Path("unused"))
        raise AssertionError("file limit was not enforced")
    except ValueError:
        pass
    with tempfile.TemporaryDirectory() as temporary:
        kit = Path(temporary)
        (kit / "sdk.dll").write_bytes(data)
        metadata = {"files": [{"path": "sdk.dll", "bytes": len(data)}],
                    "limitReasons": [], "reparseEntriesSkipped": 0}
        result = observe(metadata, kit)
        assert result["complete"] and result["bytesBudgeted"] == len(data)
        assert result["files"][0]["sha256"] == hashlib.sha256(data).hexdigest()
        assert len(result["files"][0]["matches"]) == 2
        metadata["files"][0]["path"] = "../sdk.dll"
        assert observe(metadata, kit)["files"][0]["readErrorType"] == "ValueError"
        with (kit / "large.dll").open("wb") as large:
            large.truncate(FILE_LIMIT + 1)
        metadata["files"] = [{"path": "large.dll", "bytes": FILE_LIMIT + 1}]
        assert observe(metadata, kit)["bytesBudgeted"] == 0
        try:
            (kit / "alias.dll").symlink_to(kit / "sdk.dll")
        except OSError:
            pass
        else:
            metadata["files"] = [{"path": "alias.dll", "bytes": len(data)}]
            result = observe(metadata, kit)
            assert not result["complete"] and result["files"][0]["sha256"] is None
    print("WACK SDK literal scanner self-test passed")

if __name__ == "__main__":
    if sys.argv[1:] == ["--self-test"]:
        self_test()
    else:
        metadata_path, kit, output = map(Path, sys.argv[1:])
        if metadata_path.stat().st_size > JSON_LIMIT:
            raise ValueError("metadata budget")
        result = observe(json.loads(metadata_path.read_text(encoding="utf-8")), kit)
        with output.open("xb") as target:
            target.write(encode_result(result))
'@
if ($SelfTest) {
    $scanner | python - --self-test
    if ($LASTEXITCODE -ne 0) { throw 'SDK scanner self-test failed.' }
    return
}
if (-not $OutputDirectory) { throw 'OutputDirectory is required.' }
$kit = [System.IO.Path]::GetFullPath((Join-Path ${env:ProgramFiles(x86)} 'Windows Kits/10/App Certification Kit'))
$root = Get-Item -LiteralPath $kit
if (-not $root.PSIsContainer -or ($root.Attributes -band [System.IO.FileAttributes]::ReparsePoint)) { throw 'Kit root must be a regular directory.' }
$directories = [System.Collections.Generic.Stack[System.IO.DirectoryInfo]]::new()
$directories.Push($root)
$files = [System.Collections.Generic.List[object]]::new()
$reasons = [System.Collections.Generic.List[string]]::new()
$skipped = 0; $entries = 0; $total = [long]0; $stop = $false
while ($directories.Count -gt 0 -and -not $stop) {
    foreach ($entry in $directories.Pop().EnumerateFileSystemInfos()) {
        $entries++
        if ($entries -gt 4096) { $reasons.Add('entry-count'); $stop = $true; break }
        if ($entry.Attributes -band [System.IO.FileAttributes]::ReparsePoint) { $skipped++; continue }
        if ($entry -is [System.IO.DirectoryInfo]) { $directories.Push($entry); continue }
        if ($entry -isnot [System.IO.FileInfo] -or $entry.Extension.ToLowerInvariant() -notin @('.exe', '.dll', '.mui', '.xml', '.config')) { continue }
        if ($files.Count -ge 512) { $reasons.Add('file-count'); $stop = $true; break }
        $record = @{path=[System.IO.Path]::GetRelativePath($kit, $entry.FullName); bytes=$entry.Length; fileVersion=$null; productVersion=$null}
        if ($entry.Length -gt 16MB) { $record.skipReason='file-size' }
        elseif ($entry.Length -gt 128MB - $total) { $record.skipReason='total-bytes' }
        else {
            $total += $entry.Length
            try {
                $version = [System.Diagnostics.FileVersionInfo]::GetVersionInfo($entry.FullName)
                $record.fileVersion = ([string]$version.FileVersion).Substring(0, [Math]::Min(96, ([string]$version.FileVersion).Length))
                $record.productVersion = ([string]$version.ProductVersion).Substring(0, [Math]::Min(96, ([string]$version.ProductVersion).Length))
            } catch { $record.versionErrorType = $_.Exception.GetBaseException().GetType().Name }
        }
        $files.Add($record)
    }
}
New-Item -ItemType Directory -Force -Path $OutputDirectory | Out-Null
$metadata = @{files=@($files | Sort-Object { $_.path }); limitReasons=@($reasons); reparseEntriesSkipped=$skipped} | ConvertTo-Json -Depth 5 -Compress
if ([System.Text.Encoding]::UTF8.GetByteCount($metadata) -gt 512KB) { throw 'SDK metadata exceeds its JSON budget.' }
$metadataPath = Join-Path $OutputDirectory ('.wack-sdk-metadata-' + [guid]::NewGuid().ToString('N') + '.json')
try {
    [System.IO.File]::WriteAllText($metadataPath, $metadata, [System.Text.UTF8Encoding]::new($false))
    $scanner | python - $metadataPath $kit (Join-Path $OutputDirectory 'wack-sdk-observation.json')
    if ($LASTEXITCODE -ne 0) { throw 'SDK inventory scanner failed.' }
} finally {
    if (Test-Path -LiteralPath $metadataPath) { Remove-Item -LiteralPath $metadataPath }
}
