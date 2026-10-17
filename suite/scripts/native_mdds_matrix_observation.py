"""Original MDDS matrix compile-only observation. No product patch or runtime claim."""
import importlib.util
import json
from pathlib import Path
import re
import sys

_spec=importlib.util.spec_from_file_location('mdds_base',Path(__file__).with_name('native_mdds_probe.py'))
base=importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(base)

# Actual original upstream files, including the underlying soa equality boundary.
SOURCE_PINS={
 'include/mdds/multi_type_matrix.hpp':(28768,'298d0d85be34cb9af6e0172e51c6c4748ed17900a99267fc65f0e1d812a6dd23'),
 'include/mdds/multi_type_matrix_def.inl':(24663,'48973c16a597c893b1de79689d91b11669e277e136c79050211a06ba8cc8e092'),
 'include/mdds/multi_type_vector.hpp':(395,'c564bd41256bc643aa60f55cb0f0074ed15f67b94e02e9d4312eea95c181bc21'),
 'include/mdds/multi_type_vector/soa/main.hpp':(62599,'fa23b0046758009d58e5be69856e167656a212b4d937f83b8bce6f643115cdb9'),
 'include/mdds/multi_type_vector/soa/main_def.inl':(198800,'08ac72ad06b18d746a0a7830cca74b5bbf08b2b1b46724f461c2089767b5b660'),
}
CASES=('matrix-include','matrix-builtin-equality')

def prepare(out,work,scripts):
    out,work,scripts=map(Path,(out,work,scripts))
    source=json.loads((out/'source-plan.json').read_bytes())
    if [c['name'] for c in source['cases']]!=['original','candidate']:raise ValueError('Unexpected reused source preparation')
    original=Path(source['cases'][0]['root'])
    if original.resolve()!=(work/'original').resolve() or Path(source['cases'][0]['include']).resolve()!=(original/'include').resolve():
        raise ValueError('Only the expected owned original include tree is admitted')
    files=[]
    for name,pin in SOURCE_PINS.items():
        path=original/name;data=path.read_bytes();base.exact(data,pin)
        base.write(out/'matrix-original'/name,data);files.append(base.identity(path))
    # Preserve the actual upstream trait/construction examples; no recreated implementation.
    for name in ('example/multi_type_matrix.cpp','test/multi_type_matrix/test_main.cpp'):
        base.write(out/'matrix-original'/name,(original/name).read_bytes())
    cases=[]
    for name in CASES:
        tu=scripts/(name+'.cpp');base.write(out/tu.name,tu.read_bytes())
        cases.append(dict(name=name,translationUnit=str(tu),translationUnitIdentity=base.identity(tu),
                          include=str(original/'include'),object=str(out/(name+'.obj')),
                          sourceFiles=files))
    plan=dict(schemaVersion=1,kind='original-matrix-compile-only',cases=cases,boostInclude=source['boostInclude'],
              originalMatrixUnchanged=True,oldFlatCompiled=False,candidateCompiled=False,runtimeTested=False,
              limits='Original header parsing and upstream builtin traits only; no Office SharedString/OUString specialization or Native21 outcome.')
    base.save(out/'matrix-plan.json',plan)
    return plan

def classify_compile(command,log):
    base.clean_command(command)
    if command['exitCode'] not in (0,2):raise ValueError('Unknown compiler exit or crash rejected')
    if not re.search(r'19\.51\.36260\b',log) or not re.search(r'\bARM64\b',log,re.I):raise ValueError('Exact native compiler version missing')
    errors=[line for line in log.splitlines() if re.search(r'\b(?:fatal )?error [A-Z]+\d+:',line)]
    if re.search(r'\bC1001\b|internal compiler error',log,re.I):raise ValueError('Compiler internal failure rejected')
    if command['exitCode']==0:
        if errors:raise ValueError('Successful exit with compiler errors is inconsistent')
        return 'compile-success'
    if not errors:raise ValueError('Compiler exit 2 without normal diagnostic rejected')
    for line in errors:
        match=re.search(r'multi_type_matrix_def\.inl\((93|99)\): error C2382:.*operator (==|!=).*different exception specifications',line)
        if not match:return 'unrelated-compiler-error'
        pair={'93':('256','=='),'99':('257','!=')}[match[1]]
        if pair[1]!=match[2] or not re.search(r'multi_type_matrix\.hpp\('+pair[0]+r'\): note: see declaration of .*operator '+re.escape(pair[1]),log):return 'unrelated-compiler-error'
    return 'matrix-equality-C2382'

def admit_case(out,case):
    out=Path(out);name=case['name']
    if name not in CASES:raise ValueError('Unexpected matrix case')
    command=json.loads((out/(name+'.command.json')).read_bytes())
    log=''.join((out/(name+'.'+s+'.log')).read_text(errors='replace') for s in ('stdout','stderr'))
    classification=classify_compile(command,log)
    normalized=log.replace('\\','/').casefold()
    for source in case['sourceFiles']:
        actual=base.identity(source['path'])
        if actual!=source:raise ValueError('Original matrix/underlying source drift')
        if Path(source['path']).name in ('multi_type_matrix.hpp','multi_type_matrix_def.inl'):
            if source['path'].replace('\\','/').casefold() not in normalized:raise ValueError('Expected original matrix include identity missing')
    obj=Path(case['object']);object_row=None
    if classification=='compile-success':object_row=base.object_identity(obj)
    elif obj.exists():raise ValueError('Failed compile emitted object; preserve and reject admission')
    return dict(name=name,classification=classification,command=command,object=object_row,
                runtimeTested=False,engineQualified=False,productQualified=False,baseQualified=False,
                observationAdmitted=True,compilerAccepted=classification=='compile-success')

def admit(out,name=None):
    out=Path(out);plan=json.loads((out/'matrix-plan.json').read_bytes())
    if [c['name'] for c in plan['cases']]!=list(CASES):raise ValueError('Matrix case scope differs')
    cases=[admit_case(out,c) for c in plan['cases'] if name is None or c['name']==name]
    if not cases:raise ValueError('Missing requested matrix case')
    result=dict(schemaVersion=1,kind='original-matrix-compile-only',observationAdmitted=True,cases=cases,
                runtimeTested=False,engineQualified=False,productQualified=False,baseQualified=False,
                limits=plan['limits'])
    base.save(out/(name+'-admission.json' if name else 'matrix-admission.json'),result)

if __name__=='__main__':
    if sys.argv[1]=='prepare':prepare(*sys.argv[2:])
    elif sys.argv[1]=='admit-case':admit(*sys.argv[2:])
    elif sys.argv[1]=='admit':admit(*sys.argv[2:])
    else:raise ValueError('Unexpected matrix observation phase')
