"""Strict source/proof policy; real focus behavior is exercised in tests/hop."""
import copy
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import equation_dialog_focus as focus


class EquationDialogFocusProofTests(unittest.TestCase):
    def setUp(self):
        self.helper = hashlib.sha256((ROOT / focus.HELPER).read_bytes()).hexdigest()
        self.proof = {'beforeSha256': dict(focus.INPUT_SOURCE_SHA256),
                      'afterSha256': dict(focus.OUTPUT_SOURCE_SHA256),
                      'helperSha256': self.helper}
        self.files = dict(focus.OUTPUT_SOURCE_SHA256)
        self.helpers = {focus.HELPER: self.helper}

    def test_exact_reviewed_contract(self):
        focus.validate_contract(self.proof, self.files, self.helpers)

    def test_two_source_pins_preserve_the_original_equation_output(self):
        picture='third_party/rhwp/rhwp-studio/src/ui/picture-props-dialog.ts'
        self.assertTrue(focus.SOURCE_FILES==(focus.EDITOR,picture),'Exactly two focus sources required')
        self.assertTrue(focus.INPUT_SOURCE_SHA256=={focus.EDITOR:
            '1e8c382436302ee88714ba2a57d413ffa9172572f712713ce352ea91cc74fffc',picture:
            'd7a03031ec1aca560f72603d9d06678c08efbb6235810f79e739cd5fe04c2c61'})
        self.assertTrue(focus.OUTPUT_SOURCE_SHA256=={focus.EDITOR:
            '76718c71ccb0f20f622d4a1803fcfcf5174249a01bc033d63ccb82dd65cda99e',picture:
            'fd29ccb35195c1c282f356281dfa245833efe036ae25966d1aeca4fc6eaa7823'})
        self.assertNotEqual(focus.INPUT_SOURCE_SHA256, focus.OUTPUT_SOURCE_SHA256)

    def test_each_actual_prepared_source_is_required(self):
        for source_code,name in enumerate((focus.EDITOR,
                'third_party/rhwp/rhwp-studio/src/ui/picture-props-dialog.ts')):
            for mutation in range(2):
                files=dict(self.files)
                if mutation:files[name]='0'*64
                else:files.pop(name,None)
                with self.subTest(sourceCode=source_code,mutationCode=mutation),self.assertRaises(ValueError):
                    focus.validate_contract(self.proof,files,self.helpers)

    def test_second_source_rejection_cannot_write_the_first_prepared_file(self):
        with tempfile.TemporaryDirectory()as temporary:
            source=Path(temporary)
            for name in (focus.EDITOR,'third_party/rhwp/rhwp-studio/src/ui/picture-props-dialog.ts'):
                path=source/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b'owned source\n')
            output={**focus.OUTPUT_SOURCE_SHA256,focus.EDITOR:hashlib.sha256(b'owned staged output\n').hexdigest()}
            with patch.object(focus,'OUTPUT_SOURCE_SHA256',output),patch.object(
                    focus,'transformed',side_effect=[b'owned staged output\n',ValueError()]):
                with self.assertRaises(ValueError):focus.apply(source)
            self.assertTrue(all((source/name).read_bytes()==b'owned source\n' for name in
                (focus.EDITOR,'third_party/rhwp/rhwp-studio/src/ui/picture-props-dialog.ts')))

    def test_legacy_or_coordinated_unreviewed_output_cannot_qualify(self):
        for value in (focus.INPUT_SOURCE_SHA256[focus.EDITOR], '0' * 64):
            proof = copy.deepcopy(self.proof)
            proof['afterSha256'][focus.EDITOR] = value
            with self.assertRaisesRegex(ValueError, 'reviewed'):
                focus.validate_contract(proof, {focus.EDITOR: value}, self.helpers)

    def test_missing_extra_and_forged_proof_members_are_rejected(self):
        for key in self.proof:
            proof = copy.deepcopy(self.proof)
            proof.pop(key)
            with self.assertRaises(ValueError):
                focus.validate_contract(proof, self.files, self.helpers)
        with self.assertRaises(ValueError):
            focus.validate_contract({**self.proof, 'optional': True}, self.files, self.helpers)
        for key in ('beforeSha256', 'afterSha256'):
            for replacement in ({}, {focus.EDITOR: '1' * 64},
                                {**self.proof[key], 'unrelated.ts': '2' * 64}):
                proof = copy.deepcopy(self.proof)
                proof[key] = replacement
                with self.assertRaises(ValueError):
                    focus.validate_contract(proof, self.files, self.helpers)

    def test_actual_prepared_file_and_current_helper_are_required(self):
        for files in ({}, {focus.EDITOR: '3' * 64}):
            with self.assertRaisesRegex(ValueError, 'prepared'):
                focus.validate_contract(self.proof, files, self.helpers)
        for helpers in ({}, {focus.HELPER: '4' * 64}):
            with self.assertRaisesRegex(ValueError, 'helper'):
                focus.validate_contract(self.proof, self.files, helpers)
        proof = copy.deepcopy(self.proof)
        proof['helperSha256'] = '5' * 64
        with self.assertRaisesRegex(ValueError, 'helper'):
            focus.validate_contract(proof, self.files, {focus.HELPER: '5' * 64})

    def test_nonobject_contract_inputs_are_rejected(self):
        for proof, files, helpers in ((None, self.files, self.helpers),
                                     (self.proof, None, self.helpers),
                                     (self.proof, self.files, None)):
            with self.assertRaises(ValueError):
                focus.validate_contract(proof, files, helpers)

    def test_matching_anchors_cannot_admit_unknown_source(self):
        for raw in (focus.REPLACEMENTS[0][0].encode(),
                    '\n'.join(old for old, _ in focus.REPLACEMENTS).encode()):
            with self.assertRaisesRegex(ValueError, 'input changed'):
                focus.transformed(raw)

    def test_missing_tampered_and_symlink_source_are_not_written(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary)
            path = source / focus.EDITOR
            with self.assertRaises(ValueError):
                focus.apply(source)
            path.parent.mkdir(parents=True)
            raw = focus.REPLACEMENTS[0][0].encode()
            path.write_bytes(raw)
            with self.assertRaises(ValueError):
                focus.apply(source)
            self.assertEqual(path.read_bytes(), raw)
            target = source / 'owned-source.ts'
            target.write_bytes(raw)
            path.unlink()
            path.symlink_to(target)
            with self.assertRaisesRegex(ValueError, 'regular'):
                focus.apply(source)
            self.assertEqual(target.read_bytes(), raw)


class PictureInitialFocusCallbackTests(unittest.TestCase):
    """Actual replacement callback; Chromium158 select() calls script Focus().

    Only task delivery and DOM state are synthetic. This is not browser execution
    or proof of the original0cb event timing.
    """
    def observe(self,mode):
        legacy='    setTimeout(() => this.widthInput?.select(), 50);'
        replacements=getattr(focus,'PICTURE_REPLACEMENTS',((legacy,legacy),))
        source=replacements[0][1]
        node=shutil.which('node')
        self.assertTrue(node is not None,'Existing Node runtime required')
        program=r"""
          const {readFileSync}=require('node:fs');
          const input=JSON.parse(readFileSync(0,'utf8')),tasks=[];
          const document={activeElement:null};
          const number=(code,value)=>({code,value,selection:0,selects:0,isConnected:true,visible:true,
            getClientRects(){return this.visible&&this.isConnected?[{}]:[];},
            focus(){if(this.isConnected&&this.visible)document.activeElement=this;},
            select(){this.selection=1;++this.selects;this.focus();}});
          const outside={code:0},other={code:4},close={code:3};
          const first=number(1,45),height=number(2,20);
          const owner={widthInput:first};
          owner.overlay={isConnected:true,contains:n=>n===owner.widthInput||n===height||n===close};
          document.activeElement=input.mode===8?close:outside;
          const open=Function('document','setTimeout',input.source);
          const schedule=(callback,delay)=>{if(delay!==50)throw Error();tasks.push(callback);};
          open.call(owner,document,schedule);
          if(input.mode===1){height.select();height.focus();}
          if(input.mode===3){first.focus();first.selection=2;}
          if(input.mode===4){owner.overlay.isConnected=false;first.isConnected=false;height.isConnected=false;}
          if(input.mode===5){
            first.isConnected=false;owner.widthInput=number(1,45);
            open.call(owner,document,schedule);
          }
          if(input.mode===6)first.visible=false;
          if(input.mode===7)document.activeElement=other;
          tasks[0]();
          const firstFocus=document.activeElement.code;
          if(input.mode===5)tasks[1]();
          if(input.mode===1){
            const target=document.activeElement;
            target.value=target.selection===1?25:Number(String(target.value)+'25');
          }
          process.stdout.write(JSON.stringify({focusCode:document.activeElement.code,firstFocusCode:firstFocus,
            values:[owner.widthInput.value,height.value],selects:owner.widthInput.selects,
            originalSelects:first.selects,selection:owner.widthInput.selection,tasks:tasks.length}));
        """
        result=subprocess.run([node,'-e',program],input=json.dumps({'source':source,'mode':mode}).encode(),
            stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,timeout=5,env={})
        self.assertTrue(result.returncode==0,'Source-isolated callback failed')
        row=json.loads(result.stdout)
        self.assertTrue(all(type(row[key])is int for key in
            ('focusCode','firstFocusCode','selects','originalSelects','selection','tasks')))
        self.assertTrue(type(row['values'])is list and all(type(v)is int for v in row['values']))
        return row

    def test_height_selection_then_initial_callback_cannot_redirect_insert_text(self):
        row=self.observe(1)
        self.assertTrue(row['values']==[45,25] and row['focusCode']==2 and row['selects']==0,
                        'Initial callback redirected an authored height input')

    def test_idle_opening_still_selects_the_visible_width_once(self):
        row=self.observe(2)
        self.assertTrue(row['focusCode']==1 and row['selects']==1 and row['selection']==1 and row['tasks']==1)

    def test_user_width_selection_is_preserved(self):
        row=self.observe(3)
        self.assertTrue(row['focusCode']==1 and row['selects']==0 and row['selection']==2)

    def test_hidden_opening_does_not_select_a_detached_width(self):
        row=self.observe(4)
        self.assertTrue(row['focusCode']==0 and row['selects']==0)

    def test_stale_callback_cannot_select_the_reopened_width(self):
        row=self.observe(5)
        self.assertTrue(row['firstFocusCode']==0 and row['originalSelects']==0 and row['selects']==1 and row['tasks']==2)

    def test_hidden_tab_does_not_receive_initial_selection(self):
        row=self.observe(6)
        self.assertTrue(row['focusCode']==0 and row['selects']==0)

    def test_changed_external_focus_is_preserved(self):
        row=self.observe(7)
        self.assertTrue(row['focusCode']==4 and row['selects']==0)

    def test_initial_focus_already_inside_the_dialog_is_preserved(self):
        row=self.observe(8)
        self.assertTrue(row['focusCode']==3 and row['selects']==0)


if __name__ == '__main__':
    unittest.main(verbosity=2)
