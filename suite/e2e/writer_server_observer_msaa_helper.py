"""Exclusive numeric result helper; stdio is NUL via the owned Win32 launcher.

The original read-only MSAA owner admission is not retirement/cleanup authority.
No GUI observer, UIA collector, names, text, titles, or screenshots are invoked.
"""
import json
import os
from pathlib import Path
import sys

import writer_os_accessibility as raw


class HelperError(RuntimeError):
    def __init__(self):super().__init__('Writer numeric helper failure')


PUBLIC_MAXIMA={'schemaVersion':1,'verified':1,'stageCode':14,'hresult':0xffffffff,
    'rootRole':0x7fffffff,'documentRole':0x7fffffff,'focusedRole':0x7fffffff,
    'focusedState':0x7fffffff,'focusVariantType':0xffff,'parentCount':32,
    'ia2Supported':1,'textSupported':1,'ownerBefore':1,'ownerAfter':1,
    'referencesAcquired':256,'referencesReleased':256,'variantsCreated':64,
    'variantsCleared':64,'cleanupFailure':1,'cleanupHresult':0xffffffff,'ownerReleased':1}
FOCUS_MAXIMA={'attempted':1,'returned':1,'hrObserved':1,'hr':0xffffffff,'vtObserved':1,'rejectCode':5}


def unique(pairs):
    result={}
    for key,value in pairs:
        if key in result:raise HelperError()
        result[key]=value
    return result


def public_shape(value):
    if (type(value) is not dict or value.keys()!={'schemaVersion','diagnosticOnly','acceptanceEligible','bodyReturned','observation'}
        or any(type(value[k]) is not int or value[k]!=v for k,v in
            (('schemaVersion',1),('diagnosticOnly',1),('acceptanceEligible',0),('bodyReturned',1)))):
        raise HelperError()
    observed=value['observation']
    if (type(observed) is not dict or not PUBLIC_MAXIMA.keys()<=observed.keys()
        or not observed.keys()<=PUBLIC_MAXIMA.keys()|{'focusCall'}
        or any(type(observed[k]) is not int or not 0<=observed[k]<=maximum for k,maximum in PUBLIC_MAXIMA.items())):
        raise HelperError()
    projection={k:observed[k] for k in PUBLIC_MAXIMA}
    if 'focusCall' in observed:
        focus=observed['focusCall']
        if (type(focus) is not dict or focus.keys()!=FOCUS_MAXIMA.keys()
            or any(type(focus[k]) is not int or not 0<=focus[k]<=maximum for k,maximum in FOCUS_MAXIMA.items())):
            raise HelperError()
        projection['focusCall']={k:focus[k] for k in FOCUS_MAXIMA}
    return {'schemaVersion':1,'diagnosticOnly':1,'acceptanceEligible':0,'bodyReturned':1,'observation':projection}


def validate_public(value,request):
    projection=public_shape(value)
    # Reconstruct only the caller's original private join in memory; never
    # serialize it to the result file or any public receipt.
    full={k:projection['observation'][k] for k in PUBLIC_MAXIMA}
    if 'focusCall' in projection['observation']:
        full['focusCall']=projection['observation']['focusCall']
    full['officePid']=request['officePid'];full['officeCreationTime']=request['officeCreationTime']
    full['childHwnd']=request['childHwnd']
    raw.validate(full,request)
    return projection


class RawNumericBackend:
    """Composition preserves raw methods without observe's GUI isinstance path."""
    def __init__(self,guard,record,*,raw_factory=None):
        self._inner=(raw_factory or raw.RawComBackend)(guard,record)
    def __repr__(self):return '<RawNumericBackend private>'
    def root(self,hwnd):return self._inner.root(hwnd)
    def identity(self,pointer):return self._inner.identity(pointer)
    def role(self,pointer):return self._inner.role(pointer)
    def focus(self,pointer):return self._inner.focus(pointer)
    def state(self,pointer):return self._inner.state(pointer)
    def support(self,pointer,interface):return self._inner.support(pointer,interface)
    def parent(self,pointer):return self._inner.parent(pointer)
    def close(self):return self._inner.close()


def run_raw_observation(request,*,owner_factory=None,raw_backend_factory=None):
    raw._request(request)
    value=raw.observe(request,owner_factory=owner_factory,
        backend_factory=lambda guard,record:RawNumericBackend(guard,record,raw_factory=raw_backend_factory))
    value=raw.validate(value,request)
    if 'guiFocus' in value:raise HelperError()
    observed={k:value[k] for k in PUBLIC_MAXIMA}
    if 'focusCall' in value:observed['focusCall']={k:value['focusCall'][k] for k in FOCUS_MAXIMA}
    return validate_public({'schemaVersion':1,'diagnosticOnly':1,'acceptanceEligible':0,
        'bodyReturned':1,'observation':observed},request)


def write_exclusive(path,value):
    descriptor=None
    try:
        encoded=json.dumps(public_shape(value),separators=(',',':'),allow_nan=False).encode('ascii')
        if not 0<len(encoded)<=4096:raise HelperError()
        descriptor=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,'O_BINARY',0),0o600)
        if os.write(descriptor,encoded)!=len(encoded):raise HelperError()
    except Exception:raise HelperError() from None
    finally:
        if descriptor is not None:
            try:os.close(descriptor)
            except Exception:raise HelperError() from None


def main(arguments=None):
    try:
        args=sys.argv[1:] if arguments is None else arguments
        if len(args)!=4 or args[0]!='--result' or args[2]!='--owner-json':return 2
        path=Path(args[1])
        if not path.is_absolute():return 2
        request=json.loads(args[3],object_pairs_hook=unique)
        value=run_raw_observation(request)
        write_exclusive(path,value)
        return 0
    except BaseException:
        return 3  # No request, exception text, COM error, or raw stdio output.


if __name__=='__main__':raise SystemExit(main())
