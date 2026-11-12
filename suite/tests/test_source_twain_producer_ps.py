"""Portable, component-only TWAIN producer contracts; never execute Full."""
from pathlib import Path
import hashlib
import json
import struct
import unittest

import test_source_companion_producer_ps as existing
import test_source_twain_capture as capture_fixture

DRIVER=existing.DRIVER
quote=existing.quote


class TwainProducerTests(existing.ProducerTests):
    # Existing four SPSupp tests are selected separately, not inherited twice.
    test_numeric_command_discards_streams_arguments_and_exception_text=None
    test_component_binder_requires_current_context_and_generic_native_gate_stays_closed=None
    test_full_capture_revalidation_and_separate_inventory_role_are_mandatory=None
    test_component_object_cannot_differ_from_current_owned_proof_file=None

    def fixture(self,label):
        value=capture_fixture.TwainCaptureTests('test_twain_capture_requires_exact_source_effect_and_scanner_peer')
        value.setUp();self.addCleanup(value.doCleanups)
        paths=value.fixture(label);self.assertEqual(value.run_capture(paths),0)
        return paths

    def receipt(self,paths):
        proof=paths[-1]/'source-twain-proof.json'
        return ("$p=Get-Content "+quote(proof)+" -Raw|ConvertFrom-Json\n"
            "$r=[pscustomobject]@{sourcePin=[pscustomobject]@{coreCommit='9dea406ab7695df6325b11b0e19fdca8db4b7276'};architecture='x64';sourceCommit=$p.buildBinding.sourceCommit;sourceTree=$p.buildBinding.sourceTree;sourceRun=$p.buildBinding.sourceRun;runAttempt=$p.buildBinding.runAttempt;sourceRecipeProof=[pscustomobject]@{recipeSha256=$p.buildBinding.recipeSha256};installedRuntimeStage=[pscustomobject]@{receipt=[pscustomobject]@{sha256=$p.installedArchive.stageReceiptSha256}};sourceTwainProof=$p}\n")

    def call(self,paths):
        return 'Get-OwnedSourceTwainProduct $r '+quote(paths[1])+' '+quote(paths[-1])

    def test_exact_owned_executable_is_separate_from_generic_native_admission(self):
        paths=self.fixture('owned');body=self.receipt(paths)
        body+='$row='+self.call(paths)+";if($row.role -cne 'x86CompatibilityHelper' -or $row.machine -ne 332){exit 1}\n"
        body+="$rejected=$false;try{Get-AuditedProductPeIdentity "+quote(paths[1]/'program/twain32shim.exe')+' '+quote(paths[1])+' '+quote(paths[-1])+" x64 -RequireNative|Out-Null}catch{$rejected=$true};if(-not $rejected){exit 2}\n"
        body+="$r.sourceRun=124;$rejected=$false;try{"+self.call(paths)+"|Out-Null}catch{$rejected=$true};if(-not $rejected){exit 3}\n"
        self.assertEqual(self.ps(body),0)

    def test_embedded_object_must_equal_this_run_proof(self):
        paths=self.fixture('embedded');body=self.receipt(paths)
        body+="$p.sourceProofs[0].sha256=('0'*64);$rejected=$false;try{"+self.call(paths)+"|Out-Null}catch{$rejected=$true};if(-not $rejected){exit 4}\n"
        self.assertEqual(self.ps(body),0)

    def test_current_run_recipe_stage_and_peer_metadata_are_mandatory(self):
        paths=self.fixture('context');setup=self.receipt(paths);body=''
        mutations=("$r.sourceRecipeProof.recipeSha256=('4'*64)",
                   "$r.installedRuntimeStage.receipt.sha256=('4'*64)",
                   "$r.architecture='arm64'",
                   "$p.nativePeer.role='managedAnyCpu'",
                   "$p.fullEngineQualified=$true")
        # Proof mutations are persisted identically so checks cannot succeed by
        # relying only on the embedded-object byte comparison.
        original=(paths[-1]/'source-twain-proof.json').read_bytes()
        for ordinal,mutation in enumerate(mutations):
            body+=setup+mutation+'\n'
            if mutation.startswith('$p.'):
                body+="[IO.File]::WriteAllText("+quote(paths[-1]/'source-twain-proof.json')+",(($p|ConvertTo-Json -Depth 30 -Compress)+\"`n\"),[Text.UTF8Encoding]::new($false))\n"
            body+="$rejected=$false;try{"+self.call(paths)+"|Out-Null}catch{$rejected=$true};if(-not $rejected){exit "+str(10+ordinal)+"}\n"
            body+="[IO.File]::WriteAllBytes("+quote(paths[-1]/'source-twain-proof.json')+",[Convert]::FromBase64String('"+__import__('base64').b64encode(original).decode()+"'))\n"
        self.assertEqual(self.ps(body),0)

    def test_executable_and_native_dll_shapes_are_independently_checked(self):
        cases=[('program/twain32shim.exe',0x80+22,'<H',0x2102),
               ('program/twain32shim.exe',0x98+68,'<H',3),
               ('program/twain32shim.exe',0x98+16,'<I',0x9000),
               ('program/twain32shim.exe',0x98+96+14*8,'<I',0x1600),
               ('program/twain32shim.exe',0x98+224+36,'<I',0x40000020),
               ('program/scnlo.dll',0x80+22,'<H',0x22),
               ('program/scnlo.dll',0x98+112+14*8,'<I',0x1600)]
        for ordinal,(relative,offset,fmt,number) in enumerate(cases):
            with self.subTest(case=ordinal):
                paths=self.fixture('shape-'+str(ordinal));path=paths[1]/relative
                binary=bytearray(path.read_bytes());struct.pack_into(fmt,binary,offset,number);path.write_bytes(binary)
                proof=paths[-1]/'source-twain-proof.json';p=json.loads(proof.read_text())
                row=p if relative.endswith('.exe') else p['nativePeer']
                row.update(size=len(binary),sha256=hashlib.sha256(binary).hexdigest())
                if relative.endswith('.exe'):p['linkTarget'].update(size=row['size'],sha256=row['sha256'])
                proof.write_text(json.dumps(p,sort_keys=True,separators=(',',':'))+'\n')
                body=self.receipt(paths)+"$rejected=$false;try{"+self.call(paths)+"|Out-Null}catch{$rejected=$true};if(-not $rejected){exit 5}\n"
                self.assertEqual(self.ps(body),0)

    def test_twain_capture_uses_retained_hook_evidence_and_final_revalidation(self):
        source=DRIVER.read_text()
        for required in ("$receipt.stage='source-twain-audit'", "sourceEvidenceDirectory=$sourceEvidence",
                'original=$receipt.sourceHooks.cliPublisherPolicyPlatform.evidence.original',
                'effective=$receipt.sourceHooks.cliPublisherPolicyPlatform.evidence.effective',
                "'suite/engine-build/capture_source_twain.py'", '$receipt.sourceTwainProof=',
                "$receipt.stage='revalidate-source-twain'", "@($twainArguments+'--validate')",
                '$Receipt.companionPeCount -ne 2', '$rows.Count -ne 2',
                '$ownedTwain=Get-OwnedSourceTwainProduct',
                '$inventory+=Get-OwnedSourceTwainProduct'):
            with self.subTest(contract=required):self.assertTrue(required in source,'Missing fixed TWAIN producer contract')
        capture=source[source.index("$receipt.stage='source-twain-audit'"):source.index("$receipt.stage='native-product-pe-audit'")]
        self.assertIn('-TimeoutMinutes 1 -NativeEnvironment -NumericOnly',capture)
        revalidate=source[source.index("$receipt.stage='revalidate-source-twain'"):source.index('Assert-NativeX64Qualification $receipt')]
        self.assertIn('-TimeoutMinutes 1 -NativeEnvironment -NumericOnly',revalidate)

    def test_original_spsupp_and_generic_pe_bodies_are_unchanged(self):
        source=DRIVER.read_text()
        generic=source[source.index('function Get-ProductPeIdentity('):source.index('function Save-ProductPeFailure(')]
        self.assertEqual(hashlib.sha256(generic.encode()).hexdigest(),'03a16d71f4cddf8cf24997d5e3f2c0655b449abdc4a2d0e82b2fd83f962c500d')
        spsupp=source[source.index('function Get-OwnedSourceCompanionProduct('):source.index('function Get-OwnedSourceTwainProduct(')]
        self.assertEqual(hashlib.sha256(spsupp.encode()).hexdigest(),'776697e88f154dcdd3a027e8466113da640cb62d33f979be6882793453c38c1f')

    def test_final_inventory_binds_both_native_peers_without_inflating_native_count(self):
        source=DRIVER.read_text()
        final=source[source.index('function Assert-NativeX64Qualification('):source.index('function Invoke-NativeEngineBuild(')]
        for required in ('$Receipt.sourceCompanionProof.nativeHelper','$Receipt.sourceTwainProof.nativePeer',
                "$matches[0].role -cne 'nativeX64'",'$matches[0].machine -ne 34404',
                '$matches[0].sha256 -cne $peer.sha256','$matches[0].size -ne $peer.size'):
            with self.subTest(boundary=required):self.assertTrue(required in final,'Missing native peer inventory join')
        self.assertTrue("$receipt.nativePeCount=@($inventory|Where-Object {$_.role -eq $nativeRole}).Count" in source)
