"""Explicit Cygwin source selector check, outside normal test discovery."""
from suite.tests.test_x86_companion_static_runtime import *

class GbuildSelectionTests(unittest.TestCase):
    """Evaluate exact public make macros, not C++/IDL compilation or ABI."""
    def test_both_real_recipes_select_static_only_for_the_exact_x64_msc_profile(self):
        m=load();self.assertIsNotNone(m)
        library=(FIXTURE/'solenv/gbuild/Library.mk').read_text()
        executable=(FIXTURE/'solenv/gbuild/Executable.mk').read_text()
        link=(FIXTURE/'solenv/gbuild/LinkTarget.mk').read_text()
        msc=(FIXTURE/'solenv/gbuild/platform/com_MSC_class.mk').read_text()
        def defined(text,name):
            start='define '+name+'\n';self.assertEqual(text.count(start),1)
            return start+text.split(start,1)[1].split('\nendef',1)[0]+'\nendef\n'
        remove='gb_Helper_remove_overridden_flags = '
        i=msc.index(remove);lines=msc[i:].splitlines(True);selected=[]
        for line in lines:
            selected.append(line)
            if not line.rstrip('\n').endswith('\\'):break
        macros=''.join(selected)
        self.assertNotIn('$(shell',macros);self.assertNotIn('$(file',macros)
        macros+=defined(link,'gb_LinkTarget_add_cxxflags')
        macros+=defined(link,'gb_LinkTarget_set_x86')
        self.assertIn('$(if $(filter YES,$(PE_X86)), $(CXX_X86_BINARY)',msc)
        for api,text in [('Library',library),('Executable',executable)]:
            macros+=defined(text,'gb_'+api+'__forward_to_Linktarget')
            for suffix in ('add_cxxflags','set_x86'):
                alias='gb_'+api+'_'+suffix+' = '
                selected=[row+'\n'for row in text.splitlines()if row.startswith(alias)]
                self.assertEqual(len(selected),1);macros+=''.join(selected)
        self.assertIn('$(T_CXXFLAGS) $(T_CXXFLAGS_APPEND)',link)
        with tempfile.TemporaryDirectory()as temporary:
            root=Path(temporary)
            for pin in descriptor()['sources']:
                api,target=('Library','spsupp_x86')if pin['path'].startswith('shell/')else('Executable','twain32shim')
                original=(FIXTURE/pin['path']).read_bytes();effective=m.transform(original,pin)
                for source,expected_static in [(original,False),(effective,True)]:
                    for os,cpu,com,eligible in [('WNT','X86_64','MSC',True),('WNT','AARCH64','MSC',False),('LINUX','X86_64','GCC',False)]:
                        with self.subTest(target=target,effective=expected_static,eligible=eligible):
                            recipe=root/'recipe.mk';recipe.write_bytes(source)
                            make=root/'Makefile'
                            stub='gb_LinkTarget_get_target = $(1)\ngb_'+api+'_get_linktarget = $(1)\n'
                            stub+='gb_'+api+'_add_exception_objects = OBJECTS += $(2)\n'
                            # All other target APIs are intentionally inert: no generated headers,
                            # compiler, SDK or linker are executed in this selector-only test.
                            contents=('OS='+os+'\nCPUNAME='+cpu+'\nCOM='+com+'\nENABLE_LTO=TRUE\n'+stub+macros+
                                      '\ninclude '+str(recipe)+'\n.PHONY: check '+target+' $(OBJECTS) control\ncheck: '+target+' control\n'+
                                      target+': $(OBJECTS)\n$(OBJECTS): T_CXXFLAGS=-MD\n$(OBJECTS): DEFS=-D_DLL\n'+
                                      '$(OBJECTS):\n\t$(info ARCH $(PE_X86))$(info OWNED $(call gb_Helper_remove_overridden_flags,$(DEFS) $(T_CXXFLAGS) $(T_CXXFLAGS_APPEND)))@:\n'+
                                      'control:\n\t$(info CONTROL $(call gb_Helper_remove_overridden_flags,-D_DLL -MD))@:\n')
                            make.write_text(contents)
                            result=subprocess.run(['/usr/bin/make','-rR','-n','-f',str(make),'check'],env={'PATH':'/usr/bin:/bin'},stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,timeout=5)
                            self.assertEqual(result.returncode,0)
                            rows=[line.split()for line in result.stdout.decode('ascii').splitlines()if line.startswith('OWNED ')]
                            self.assertEqual(len(rows),4 if api=='Library'else 1)
                            self.assertEqual(result.stdout.decode('ascii').splitlines().count('ARCH YES'),len(rows))
                            for row in rows:self.assertEqual(row[1:],['-GL-']+(['-U_DLL','-MT']if expected_static and eligible else['-D_DLL','-MD']))
                            self.assertIn(b'CONTROL -D_DLL -MD',b' '.join(result.stdout.split()))
