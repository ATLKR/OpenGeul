"""Bounded native-disassembly syntax classifier; never follows a target or proves execution."""
import re


REASON_CODES=frozenset(('classification-failure','disassembly-size','instruction-range',
    'line-size','unsupported-output-line','instruction-coverage','unsupported-mnemonic',
    'unsupported-operands','call-count','unsupported-address-syntax','target-rva',
    'unsupported-call-register','fixture-direct-target-mismatch'))


class ClassificationError(ValueError):
    def __init__(self, reason):
        self.reason_code = reason if type(reason) is str and reason in REASON_CODES else 'classification-failure'
        super().__init__(self.reason_code)


def require(ok, reason):
    if not ok: raise ClassificationError(reason)


# Deliberately finite grammar: unfamiliar native output is an inconclusive input,
# not a reason to guess an opcode's effects. Only adjacent import flow is modeled.
MNEMONICS=set('adc adcs add adds adr adrp and ands asr b bic bl blr br cbnz cbz ccmp cinc cmn cmp csel cset csinc csinv csneg eor ldar ldaxr ldp ldr ldrb ldrh ldrsb ldrsh ldrsw ldur ldxr lsl lsr madd mov movk movn movz mrs msr mul mvn neg nop orn orr ret sbc sdiv stlr stlxr stp str strb strh stur stxr sub subs sxtb sxth sxtw tbnz tbz tst ubfx udiv uxtb uxth'.split())
CONDITIONS=set('eq ne cs hs cc lo mi pl vs vc hi ls ge lt gt le al nv'.split())
ROW=re.compile(r'^\s*([0-9A-Fa-f]{8,16}):\s+([A-Za-z][A-Za-z0-9.]*)\s*(.*?)\s*$')
REGISTER=r'x(?:[12]?[0-9]|30)'


def address(value):
    require(bool(re.fullmatch(r'(?:0x)?[0-9a-fA-F]{1,16}',value)), 'unsupported-address-syntax')
    return int(value,16)


def parse_and_classify(text, *, image_base, function_range, condition_iat=None, fixture_target=None):
    require(type(text) is str and len(text.encode('utf-8')) <= 256*1024, 'disassembly-size')
    begin,end=function_range['beginRva'],function_range['endRvaExclusive']
    require(type(image_base) is int and 0 < image_base < 2**64 and
            type(begin) is int and type(end) is int and 0 < begin < end <= 2**32 and
            begin%4 == end%4 == 0 and (end-begin)//4 <= 25, 'instruction-range')
    rows=[]
    for line in text.splitlines():
        require(len(line)<=1024,'line-size')
        if not line.strip():continue
        match=ROW.fullmatch(line)
        if not match:
            # Fixed tool boilerplate, not arbitrary ignored lines or instructions.
            require(bool(re.fullmatch(r'(?:Microsoft \(R\) COFF/PE Dumper Version [0-9.]+|Copyright \(C\) Microsoft Corporation\.  All rights reserved\.|Dump of file .+|File Type: DLL|\s*Summary|\s*[0-9A-Fa-f]+ \.[A-Za-z0-9_$]+|[A-Za-z_?$@][A-Za-z0-9_?$@]*:)',line)), 'unsupported-output-line')
            continue
        va,mnemonic,operands=match.groups();pc=int(va,16)-image_base;mnemonic=mnemonic.lower();operands=operands.lower()
        require(pc == begin+4*len(rows) and pc < end, 'instruction-coverage')
        require(mnemonic in MNEMONICS or (mnemonic.startswith('b.') and mnemonic[2:] in CONDITIONS),'unsupported-mnemonic')
        require(bool(re.fullmatch(r'[a-z0-9#x,\[\]!+\- .]*',operands)), 'unsupported-operands')
        rows.append((pc,mnemonic,operands))
    require(len(rows)==(end-begin)//4,'instruction-coverage')
    control_flow = any(m in ('b','br','cbz','cbnz','tbz','tbnz') or m.startswith('b.') for _,m,_ in rows)
    calls=[]
    for i,(pc,mnemonic,operands) in enumerate(rows):
        if mnemonic not in ('bl','blr'):continue
        require(len(calls)<8,'call-count')
        call=dict(callRva=pc,returnRva=pc+4,kind='direct' if mnemonic=='bl' else 'indirect',flow='unproved-register-flow')
        if mnemonic=='bl':
            target=address(operands)-image_base
            require(0 <= target < 2**32 and target%4==0,'target-rva')
            call.update(targetRva=target,targetWithinRange=begin<=target<end,flow='direct-target-not-followed')
        else:
            require(bool(re.fullmatch(REGISTER,operands)),'unsupported-call-register')
            if i>=2 and rows[i-2][1]=='adrp' and rows[i-1][1]=='ldr':
                adrp=re.fullmatch('('+REGISTER+r'),\s*((?:0x)?[0-9a-f]{1,16})',rows[i-2][2])
                load=re.fullmatch('('+REGISTER+r'),\s*\[('+REGISTER+r'),\s*#(0x[0-9a-f]+|[0-9]+)\]',rows[i-1][2])
                if adrp and load and adrp[1]==load[2] and load[1]==operands:
                    page=address(adrp[2]);offset=int(load[3],16 if load[3].startswith('0x') else 10)
                    if page%4096==0 and 0<=offset<=32760 and offset%8==0 and page+offset-image_base==condition_iat:
                        call['flow']='adjacent-known-condition-import'
                        call['importName']='sal3.dll!osl_waitCondition'
        if mnemonic=='blr' and control_flow:
            call['flow']='unproved-control-flow'
            call.pop('importName',None)
        calls.append(call)
    result=dict(status='classified',complete=True,instructionCount=len(rows),callCount=len(calls),calls=calls,
                attributionProved=False,flowScope='adjacent-only-no-control-flow-proof',fixtureValidated=False)
    if fixture_target is not None:
        require(type(fixture_target) is int and len(calls)==1 and calls[0]['kind']=='direct' and calls[0]['targetRva']==fixture_target,'fixture-direct-target-mismatch')
        result['fixtureValidated']=True
    return result
