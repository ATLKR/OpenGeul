# Dedicated, profile-bound ATL build-input classification. This does not alter
# the shared strict JNI import-library reader or admit ARM64EC product code.
function Get-AtlPayloadHash([byte[]]$Data,[int]$Offset,[int]$Count) {
    $hasher=[Security.Cryptography.SHA256]::Create()
    try {return [Convert]::ToHexString($hasher.ComputeHash($Data,$Offset,$Count)).ToLowerInvariant()}
    finally {$hasher.Dispose()}
}

function Get-AtlMemberKey([string]$Name) {return $Name.Replace('\','/').ToLowerInvariant()}

function Read-AtlStaticArchive([string]$Path,$Profile) {
    Assert-UnlinkedPath $Path
    $file=Get-Item -LiteralPath $Path -Force
    if($file.PSIsContainer -or $file.Length -lt 8 -or $file.Length -gt 67108864) {throw 'ATL archive requires a bounded regular file.'}
    [byte[]]$data=[IO.File]::ReadAllBytes($Path)
    $hash=Get-AtlPayloadHash $data 0 $data.Length
    if($data.Length -ne $Profile.bytes -or $hash -cne $Profile.sha256 -or @($Profile.members).Count -lt 1 -or @($Profile.members).Count -gt 4096) {throw 'ATL archive profile byte/hash/member-count mismatch.'}
    if([Text.Encoding]::ASCII.GetString($data,0,8) -cne "!<arch>`n") {throw 'ATL archive signature is invalid.'}
    [long]$offset=8;$members=@();$longnames=$null
    while($offset -lt $data.Length) {
        if($members.Count -ge 4096 -or $offset+60 -gt $data.Length -or $data[[int]$offset+58] -ne 96 -or $data[[int]$offset+59] -ne 10) {throw 'ATL archive member header is truncated or invalid.'}
        $raw=[Text.Encoding]::ASCII.GetString($data,[int]$offset,16).TrimEnd(' ')
        $sizeText=[Text.Encoding]::ASCII.GetString($data,[int]$offset+48,10).Trim(' ')
        [long]$size=0
        if($sizeText -cnotmatch '^\d+$' -or -not [long]::TryParse($sizeText,[ref]$size) -or $size -gt $data.Length -or $offset+60+$size -gt $data.Length) {throw 'ATL archive member payload bounds are invalid.'}
        $payload=[int]$offset+60
        $member=[ordered]@{ordinal=$members.Count;headerOffset=$offset;payloadOffset=$payload;rawName=$raw;resolvedName=$null;
            payloadBytes=$size;payloadSha256=(Get-AtlPayloadHash $data $payload ([int]$size));kind=$null;machine=$null;coffHeader=$null}
        if($raw -ceq '//') {
            if($null -ne $longnames) {throw 'ATL archive has duplicate longnames metadata.'}
            $longnames=$member
        }
        $members+=,$member
        $offset+=60+$size
        if($offset%2) {
            if($offset -ge $data.Length -or $data[[int]$offset] -ne 10) {throw 'ATL archive padding is missing or invalid.'}
            $offset++
        }
    }
    if($offset -ne $data.Length -or $members.Count -ne @($Profile.members).Count) {throw 'ATL archive profile member-count/end mismatch.'}
    $objectNames=@{};$aa64=0;$ec=0
    foreach($member in $members) {
        $raw=$member.rawName;$payload=[int]$member.payloadOffset;$size=[int]$member.payloadBytes
        if($raw -ceq '/' -and $member.ordinal -in @(0,1)) {$member.kind='archiveIndexMetadata';$member.resolvedName=$raw}
        elseif($raw -ceq '//') {$member.kind='longnamesMetadata';$member.resolvedName=$raw}
        elseif($raw -ceq '/<ECSYMBOLS>/') {$member.kind='ecSymbolIndexMetadata';$member.resolvedName=$raw}
        else {
            if($raw.StartsWith('/')) {
                if($raw -cnotmatch '^/(\d+)$') {throw 'Unsupported ATL archive metadata member.'}
                [long]$nameOffset=0
                if(-not [long]::TryParse($Matches[1],[ref]$nameOffset) -or $null -eq $longnames -or $nameOffset -ge $longnames.payloadBytes -or
                    ($nameOffset -gt 0 -and $data[[int]($longnames.payloadOffset+$nameOffset-1)] -ne 0)) {throw 'ATL longname reference is invalid.'}
                $start=[int]($longnames.payloadOffset+$nameOffset);$end=$start;$bound=[int]($longnames.payloadOffset+$longnames.payloadBytes)
                while($end -lt $bound -and $data[$end] -ne 0 -and $end-$start -le 512) {$end++}
                if($end -ge $bound -or $end-$start -le 0 -or $end-$start -gt 512) {throw 'ATL longname is unterminated or exceeds its bound.'}
                $member.resolvedName=[Text.Encoding]::ASCII.GetString($data,$start,$end-$start)
            } else {$member.resolvedName=$raw.TrimEnd('/')}
            $nameKey=Get-AtlMemberKey $member.resolvedName
            if(-not $nameKey -or $objectNames.ContainsKey($nameKey)) {throw 'ATL ordinary member full name is missing or duplicated.'}
            $objectNames[$nameKey]=$true
            if($size -lt 20) {throw 'ATL ordinary COFF header is truncated.'}
            $machine=[int][BitConverter]::ToUInt16($data,$payload)
            if($machine -notin @(0xaa64,0xa641)) {throw 'Unsupported ATL COFF machine or object format.'}
            $sections=[int][BitConverter]::ToUInt16($data,$payload+2)
            [long]$symbols=[BitConverter]::ToUInt32($data,$payload+12)
            [long]$symbolOffset=[BitConverter]::ToUInt32($data,$payload+8)
            if([BitConverter]::ToUInt16($data,$payload+16) -ne 0 -or $sections -gt 4096 -or 20+40*$sections -gt $size) {throw 'ATL COFF section headers are unsupported or out of bounds.'}
            for($index=0;$index -lt $sections;$index++) {
                $section=$payload+20+40*$index
                [long]$rawSize=[BitConverter]::ToUInt32($data,$section+16);[long]$rawOffset=[BitConverter]::ToUInt32($data,$section+20)
                [long]$relocOffset=[BitConverter]::ToUInt32($data,$section+24);[long]$lineOffset=[BitConverter]::ToUInt32($data,$section+28)
                $relocs=[int][BitConverter]::ToUInt16($data,$section+32);$lines=[int][BitConverter]::ToUInt16($data,$section+34)
                $flags=[BitConverter]::ToUInt32($data,$section+36)
                if(($flags -band 0x1000000) -or ($rawSize -gt 0 -and $rawOffset -eq 0 -and -not($flags -band 0x80)) -or
                    ($rawOffset -gt 0 -and ($rawOffset -lt 20+40*$sections -or $rawOffset+$rawSize -gt $size)) -or
                    ($relocs -gt 0 -and ($relocOffset -lt 20+40*$sections -or $relocOffset+10*$relocs -gt $size)) -or
                    ($lines -gt 0 -and ($lineOffset -lt 20+40*$sections -or $lineOffset+6*$lines -gt $size))) {throw 'ATL COFF section data/relocation bounds or format are unsupported.'}
            }
            if($symbolOffset -eq 0) {
                if($symbols -ne 0) {throw 'ATL COFF symbols have no table offset.'}
            } else {
                [long]$strings=$symbolOffset+18*$symbols
                if($symbolOffset -lt 20+40*$sections -or $strings+4 -gt $size) {throw 'ATL COFF symbol table is out of bounds.'}
                [long]$stringBytes=[BitConverter]::ToUInt32($data,$payload+[int]$strings)
                if($stringBytes -lt 4 -or $strings+$stringBytes -gt $size) {throw 'ATL COFF string table is out of bounds.'}
            }
            $member.kind='ordinaryCoffObject';$member.machine=$machine
            $member.coffHeader=[ordered]@{machine=$machine;sections=$sections;symbolTableOffset=$symbolOffset;symbols=$symbols}
            if($machine -eq 0xaa64) {$aa64++} else {$ec++}
        }
        $pin=$Profile.members[[int]$member.ordinal]
        foreach($key in @('ordinal','headerOffset','payloadOffset','rawName','resolvedName','payloadBytes','payloadSha256','kind','machine')) {
            if($member[$key] -cne $pin.$key) {throw "ATL member profile mismatch: ordinal $($member.ordinal), field $key."}
        }
    }
    if($aa64 -lt 1 -or $aa64 -ne $Profile.aa64ObjectCount -or $ec -ne $Profile.arm64EcObjectCount) {throw 'ATL archive profile object counts do not match.'}
    return [ordered]@{path=[IO.Path]::GetFullPath($Path);bytes=$data.Length;sha256=$hash;profileKind=$Profile.kind;status='classified-static-input';
        readyForNativeLinkMeasurement=$true;knownMixedVariantInput=($ec -gt 0);allCodeMembersNativeArm64=($ec -eq 0);
        machines=@($members|Where-Object kind -eq 'ordinaryCoffObject'|ForEach-Object {$_.machine}|Sort-Object -Unique);
        aa64ObjectCount=$aa64;arm64EcObjectCount=$ec;members=$members;nativeConsumedOnlyVerified=$null}
}

function Get-AtlStaticLibrary([string]$Path,$Profile) {
    $record=[ordered]@{path=[IO.Path]::GetFullPath($Path);status='missing';bytes=$null;sha256=$null;machines=$null;
        readyForNativeLinkMeasurement=$false;nativeConsumedOnlyVerified=$null;error=$null}
    try {
        Assert-UnlinkedPath $Path
        if(-not(Test-Path -LiteralPath $Path)) {return $record}
        $file=Get-Item -LiteralPath $Path -Force
        if($file.PSIsContainer -or $file.Length -gt 67108864) {throw 'ATL static archive requires a bounded regular file.'}
        $record.bytes=$file.Length;$record.sha256=(Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
        return Read-AtlStaticArchive $Path $Profile
    } catch {$record.status='rejected';$record.error=$_.Exception.Message;return $record}
}

function Assert-AtlNativeConsumption([string[]]$Logs,[string]$Map,$Library) {
    if($Library.status -cne 'classified-static-input' -or $Library.readyForNativeLinkMeasurement -ne $true) {throw 'ATL consumption needs a classified exact static input.'}
    Confirm-FileIdentity $Library.path $Library.bytes SHA256 $Library.sha256|Out-Null
    $archiveKey=Get-AtlMemberKey ([IO.Path]::GetFullPath($Library.path))
    $objects=@($Library.members|Where-Object kind -eq 'ordinaryCoffObject')
    $consumed=@();$seen=@{}
    foreach($log in $Logs) {
        $lines=[IO.File]::ReadAllText($log) -split "`n"
        for($index=0;$index -lt $lines.Count;$index++) {
            $line=$lines[$index].TrimEnd("`r")
            if($line -notmatch '^\s*Loaded\b' -or $line -notmatch '(?i)atls(?:\.lib)?\b') {continue}
            if($line -notmatch '^\s*Loaded\s+(.+?atls\.lib)\(([^)]+)\)\s*$') {throw 'Unparsed selected-atls Loaded evidence is inconclusive.'}
            $loadedArchive=$Matches[1].Trim();$loadedName=$Matches[2]
            if((Get-AtlMemberKey $loadedArchive) -cne $archiveKey) {throw 'Loaded atls archive path differs from the classified selected input.'}
            $memberKey=Get-AtlMemberKey $loadedName
            $matchesByName=@($objects|Where-Object {(Get-AtlMemberKey $_.resolvedName) -ceq $memberKey})
            if($matchesByName.Count -ne 1) {throw 'Loaded ATL full member name is unresolved or ambiguous; basename/symbol fallback is not implemented.'}
            $member=$matchesByName[0]
            if($member.machine -ne 0xaa64 -or $seen.ContainsKey([string]$member.headerOffset)) {throw 'Consumed ATL member is non-AA64 or its Loaded evidence is duplicated.'}
            $seen[[string]$member.headerOffset]=$true
            $consumed+=,[ordered]@{ordinal=$member.ordinal;resolvedName=$member.resolvedName;headerOffset=$member.headerOffset;
                payloadOffset=$member.payloadOffset;payloadBytes=$member.payloadBytes;payloadSha256=$member.payloadSha256;machine=$member.machine;
                joinMethod='exact-full-archive-member-name';log=$log;physicalLfLine=$index+1;line=$line}
        }
    }
    if(-not $consumed.Count) {throw 'No selected-atls consumed member is proved.'}
    Assert-UnlinkedPath $Map
    if(-not(Test-Path -LiteralPath $Map -PathType Leaf) -or (Get-Item -LiteralPath $Map).Length -gt 16777216) {throw 'Bounded native ATL map evidence is missing.'}
    $mapSeen=@{};$mapRows=@();$lines=[IO.File]::ReadAllText($Map) -split "`n"
    for($index=0;$index -lt $lines.Count;$index++) {
        $line=$lines[$index].TrimEnd("`r")
        if($line -notmatch '(?i)atls(?:\.lib)?:') {continue}
        if($line -notmatch '^\s*[0-9a-f]+:[0-9a-f]+\s+\S+\s+[0-9a-f]+(?:\s+[fi])*\s+(?:\S*[\\/])?atls(?:\.lib)?:(.+?)\s*$') {throw 'Unparsed selected-atls map contribution is inconclusive.'}
        $mapKey=Get-AtlMemberKey $Matches[1]
        $mapped=@($objects|Where-Object {(Get-AtlMemberKey $_.resolvedName) -ceq $mapKey})
        if($mapped.Count -ne 1 -or $mapped[0].machine -ne 0xaa64 -or -not $seen.ContainsKey([string]$mapped[0].headerOffset)) {throw 'ATL map member is ambiguous, non-AA64 or unaccounted for by Loaded evidence.'}
        $mapSeen[[string]$mapped[0].headerOffset]=$true
        $mapRows+=,[ordered]@{log=$Map;physicalLfLine=$index+1;line=$line;headerOffset=$mapped[0].headerOffset}
    }
    if($mapSeen.Count -ne $seen.Count) {throw 'ATL Loaded/map member coverage is incomplete.'}
    Confirm-FileIdentity $Library.path $Library.bytes SHA256 $Library.sha256|Out-Null
    return [ordered]@{nativeConsumedOnlyVerified=$true;archivePath=$Library.path;archiveBytes=$Library.bytes;archiveSha256=$Library.sha256;
        consumedMembers=$consumed;mapContributions=$mapRows;unparsedSelectedArchiveLoads=0;symbolFallbackImplemented=$false}
}
