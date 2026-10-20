"""Render finite authentic GNU make source replay; never qualify product code."""
import argparse
import hashlib
import json
import pathlib
import re

MANIFEST_SHA256 = '1b059a3171fc7538f47fd6bfc954d3e0659d182ce8807befca503fb6ece2a031'


def verified_inputs(data):
    data = pathlib.Path(data)
    manifest_bytes = (data/'source.json').read_bytes()
    if hashlib.sha256(manifest_bytes).hexdigest() != MANIFEST_SHA256:
        raise ValueError('fixture identity: source manifest')
    manifest = json.loads(manifest_bytes)
    for item in manifest['members']:
        raw = (data/item['fixture']).read_bytes()
        if len(raw) != item['fixtureBytes'] or hashlib.sha256(raw).hexdigest() != item['fixtureSha256']:
            raise ValueError('fixture identity: '+item['fixture'])
    return manifest


def prepare(data, output, unix_data=None, unix_output=None):
    data, output = pathlib.Path(data), pathlib.Path(output)
    manifest = verified_inputs(data)
    unix_data = unix_data or data.resolve().as_posix()
    unix_output = unix_output or output.resolve().as_posix()
    for value in (unix_data, unix_output):
        if not re.fullmatch(r'[/A-Za-z0-9_.:-]+', value):
            raise ValueError('Controlled make path requires simple absolute spelling')
    if (output/'control.mk').exists() or (output/'control-input-receipt.json').exists():
        raise FileExistsError('Preserve original control outputs')
    text = '''# Diagnostic finite bindings only. All selected upstream macro bodies remain exact.
.DEFAULT_GOAL := all
SHELL := /bin/sh
true := TRUE
OS := WNT
MERGELIBS := TRUE
MERGELIBS_MORE :=
CROSS_COMPILING :=
gb_FULLDEPS :=
SOVERSIONSCRIPT :=
TARGETTYPE := Library
gb_BUILD_HELPER_LIBS :=
# Unrelated optional features are absent in this finite control; avmedia is unconditional.
gb_Helper_optional =
gb_Output_error = $(error $(1))
gb_Library_VALIDGROUPS := OOO
gb_Library_VALIDGROUPS_INSTALLED := OOO
# Finite fixture filename/layer registry; authentic tuple/selection macros are below.
gb_Library_get_filename = $(1)lo.dll
gb_Library_get_instdir = $(INSTDIR)/program
gb_LinkTarget__command = $(error Unexpected direct native linker branch)
# Object-list bookkeeping adapter records its argument without a linker or scheduler.
gb_LinkTarget__command_objectlist = printf '%s\\n' '$(1)' > $(WORKDIR)/objectlist-observation.txt
WORKDIR := @OUTPUT@
INSTDIR := @OUTPUT@/instdir
include @DATA@/pre_MergedLibsList.mk
include @DATA@/target-location.mk
include @DATA@/library-runtime-name.mk
include @DATA@/linktarget-command.mk
include @DATA@/install-registration.mk
$(eval $(call gb_Helper_register_libraries_for_install,OOO,ooo,avmedia merged standalone))
.PHONY: all
all: $(call gb_Library_get_linktarget_target,avmedia)
\tprintf '%s\\n' '$(strip $(gb_Library_OOO))' '$(strip $(gb_Library_MODULE_ooo))' > $(WORKDIR)/installation-selection.txt
\tprintf '%s\\n' '$(call gb_Library_get_linktarget,avmedia)' > $(WORKDIR)/target-tuple.txt
$(call gb_Library_get_linktarget_target,avmedia):
\t$(call gb_LinkTarget__command_impl,$@,$(call gb_Library__get_workdir_linktargetname,avmedia))
'''.replace('@DATA@', unix_data).replace('@OUTPUT@', unix_output)
    receipt = {'schemaVersion':1, 'scope':'upstream-source-replay-only',
               'native28DllCauseProven':False, 'fullEngineQualified':False,
               'sourceManifestSha256':MANIFEST_SHA256, 'inputs':manifest,
               'unixData':unix_data, 'unixOutput':unix_output,
               'adapters':'Finite registry/OOO layer, no optional features, no build helpers, no deps, no version script, objectlist observation only. No actual full build scheduler or native linker.'}
    with (output/'control.mk').open('x', encoding='utf-8', newline='\n') as file:
        file.write(text)
    with (output/'control-input-receipt.json').open('x', encoding='utf-8', newline='\n') as file:
        json.dump(receipt,file,indent=2);file.write('\n')
    return receipt


if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--data',required=True)
    parser.add_argument('--output',required=True)
    parser.add_argument('--unix-data',required=True)
    parser.add_argument('--unix-output',required=True)
    args=parser.parse_args()
    prepare(args.data,args.output,args.unix_data,args.unix_output)
