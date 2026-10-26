"""Compile the actual adapter against deterministic COM faults, without a desktop."""
from pathlib import Path
import os
import shutil
import subprocess
import tempfile
import unittest
from native_executable_cleanup import remove_completed_image


class CompartmentAdapterTests(unittest.TestCase):
    def test_actual_adapter_balances_refs_and_rejects_nested_or_untyped_callbacks(self):
        compiler = shutil.which('g++') or shutil.which('clang++')
        if not compiler:
            self.skipTest('Portable C++ compiler unavailable')
        stub = r'''
#pragma once
#include <cstdint>
#define STDMETHODCALLTYPE
#define WINAPI
#define __uuidof(T) IID_##T
using HRESULT=int32_t;using LONG=int32_t;using ULONG=uint32_t;using DWORD=uint32_t;
using HMODULE=void*;using LPCWSTR=const wchar_t*;using GUID=int;using REFGUID=const GUID&;using REFIID=const GUID&;
constexpr HRESULT S_OK=0,E_POINTER=-1,E_NOINTERFACE=-2,E_FAIL=-3;
enum {IID_IUnknown=1,IID_ITfCompartmentEventSink,IID_ITfCompartmentMgr,IID_ITfSource,
      GUID_COMPARTMENT_KEYBOARD_OPENCLOSE,GET_MODULE_HANDLE_EX_FLAG_PIN=1,
      GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS=4,VT_I4=3,VT_BSTR=8};
constexpr DWORD TF_INVALID_COOKIE=0xffffffffu;
inline bool IsEqualIID(REFIID a,REFIID b){return a==b;}
inline bool IsEqualGUID(REFGUID a,REFGUID b){return a==b;}
inline LONG InterlockedIncrement(volatile LONG* p){return ++*p;}
inline LONG InterlockedDecrement(volatile LONG* p){return --*p;}
inline LONG InterlockedExchange(volatile LONG* p,LONG v){LONG old=*p;*p=v;return old;}
inline LONG InterlockedCompareExchange(volatile LONG* p,LONG v,LONG expected){LONG old=*p;if(old==expected)*p=v;return old;}
struct IUnknown{virtual HRESULT QueryInterface(REFIID,void**)=0;virtual ULONG AddRef()=0;virtual ULONG Release()=0;};
struct ITfCompartmentEventSink:IUnknown{virtual HRESULT OnChange(REFGUID)=0;};
struct VARIANT{unsigned short vt;LONG lVal;};
inline void VariantInit(VARIANT* p){p->vt=0;p->lVal=0;}
HRESULT VariantClear(VARIANT*);
struct ITfThreadMgr:IUnknown{};
struct IEnumGUID:IUnknown{virtual HRESULT Next(ULONG,GUID*,ULONG*)=0;};
struct ITfCompartment:IUnknown{virtual HRESULT GetValue(VARIANT*)=0;};
struct ITfCompartmentMgr:IUnknown{virtual HRESULT EnumCompartments(IEnumGUID**)=0;virtual HRESULT GetCompartment(REFGUID,ITfCompartment**)=0;};
struct ITfSource:IUnknown{virtual HRESULT AdviseSink(REFIID,IUnknown*,DWORD*)=0;virtual HRESULT UnadviseSink(DWORD)=0;};
using FARPROC=void(*)();
HMODULE GetModuleHandleW(LPCWSTR);FARPROC GetProcAddress(HMODULE,const char*);
int GetModuleHandleExW(DWORD,LPCWSTR,HMODULE*);
'''
        code = r'''
#include <cassert>
#include <cstring>
#include "ime_compartment_windows.h"
using namespace opengeul_ime;
unsigned clears=0,pins=0;bool failClear=false;
HRESULT VariantClear(VARIANT* v){++clears;if(failClear)return E_FAIL;v->vt=0;return S_OK;}
HMODULE GetModuleHandleW(LPCWSTR){return reinterpret_cast<HMODULE>(9);}
int GetModuleHandleExW(DWORD flags,LPCWSTR address,HMODULE* out){
 assert(flags==(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS|GET_MODULE_HANDLE_EX_FLAG_PIN) && address);
 ++pins;*out=reinterpret_cast<HMODULE>(7);return 1;}
struct Object final:ITfThreadMgr,ITfCompartmentMgr,IEnumGUID,ITfCompartment,ITfSource{
 unsigned refs=0,reads=0,unadvises=0;bool nested=false,failUnadvise=false,wrongType=false,preAck=false,throwValue=false;
 int value=1;ITfCompartmentEventSink* sink=nullptr;
 HRESULT QueryInterface(REFIID id,void** out)override{
  *out=nullptr;if(id==IID_ITfCompartmentMgr)*out=static_cast<ITfCompartmentMgr*>(this);
  if(id==IID_ITfSource)*out=static_cast<ITfSource*>(this);
  if(!*out)return E_NOINTERFACE;
  AddRef();return S_OK;}
 ULONG AddRef()override{return ++refs;}ULONG Release()override{assert(refs);return --refs;}
 HRESULT EnumCompartments(IEnumGUID** out)override{*out=this;AddRef();return S_OK;}
 HRESULT Next(ULONG n,GUID* g,ULONG* fetched)override{assert(n==1);*g=GUID_COMPARTMENT_KEYBOARD_OPENCLOSE;*fetched=1;return S_OK;}
 HRESULT GetCompartment(REFGUID g,ITfCompartment** out)override{
  assert(g==GUID_COMPARTMENT_KEYBOARD_OPENCLOSE);*out=this;AddRef();return S_OK;}
 HRESULT GetValue(VARIANT* v)override{
  ++reads;v->vt=wrongType?VT_BSTR:VT_I4;v->lVal=value;
  if(throwValue)throw 17;
  if(nested){nested=false;assert(sink);sink->OnChange(GUID_COMPARTMENT_KEYBOARD_OPENCLOSE);}return S_OK;}
 HRESULT AdviseSink(REFIID id,IUnknown* s,DWORD* cookie)override{
  assert(!sink && id==IID_ITfCompartmentEventSink);
  assert(s->QueryInterface(id,reinterpret_cast<void**>(&sink))==S_OK);*cookie=71;
  if(preAck)sink->OnChange(GUID_COMPARTMENT_KEYBOARD_OPENCLOSE);
  return S_OK;}
 HRESULT UnadviseSink(DWORD cookie)override{
  assert(cookie==71 && sink);++unadvises;if(failUnadvise)return E_FAIL;
  sink->Release();sink=nullptr;return S_OK;}
};
Object* object=nullptr;
HRESULT GetExisting(ITfThreadMgr** out){assert(object);*out=object;object->AddRef();return S_OK;}
FARPROC GetProcAddress(HMODULE h,const char* name){assert(h && !std::strcmp(name,"TF_GetThreadMgr"));return reinterpret_cast<FARPROC>(&GetExisting);}
struct Host{
 CompartmentLeaseRecord& r;unsigned captures=0;bool sameThread=true;
 bool CommandBoundary(){return true;}
 bool CallbackBoundary(){return !r.disabled && !r.rejected && r.activeCallbacks==1;}
 bool SameCallbackThread(){return sameThread;}
 void RejectForeignCallback(){assert(r.activeCallbacks==1);RejectCompartment(r,LeaseCallback);}
 void RejectCallbackException()noexcept{RejectCompartment(r,LeaseCallback);}
 bool ClaimCallback(){return ClaimCompartment(r,true,true,3,false,
    InterlockedCompareExchange(reinterpret_cast<volatile LONG*>(&r.activeCallbacks),0,0));}
 void CaptureCallback(){assert(CallbackBoundary());++captures;}
};
int main(){
 for(unsigned fault=0;fault<8;++fault){
  Object o;object=&o;CompartmentLeaseRecord r{};CompartmentApiReceipt e{};Host h{r};
  OwnedCompartmentSink<Host> sink(h,r,e);o.preAck=true;
  failClear=fault==6;
  const bool installed=InstallCompartment(sink,r);
  failClear=false;
  if(fault==6){assert(!installed);assert(!DisconnectCompartment(sink,r));
   assert(!r.released && e.referencesReleased==0);continue;}
  assert(installed);assert(e.referencesAcquired==5 && e.referencesReleased==0);
  assert(e.sinkReferences==2 && o.reads==1 && !r.activeCallbacks && !h.captures);
  void* unknown=reinterpret_cast<void*>(1);assert(sink.QueryInterface(99,&unknown)==E_NOINTERFACE && !unknown);
  assert(ArmCompartment(r,true));o.value=0;
  if(fault==1)o.nested=true;
  if(fault==2)o.wrongType=true;
  if(fault==3)h.sameThread=false;
  failClear=fault==5;
  o.throwValue=fault==7;
  assert(sink.OnChange(GUID_COMPARTMENT_KEYBOARD_OPENCLOSE)==S_OK);
  failClear=false;
  assert(!r.activeCallbacks);assert(h.captures==((fault==0 || fault==4)?1u:0u));
  if(fault==1 || fault==3)assert(r.disabled && r.rejected);
  const auto reads=o.reads;o.wrongType=false;h.sameThread=true;
  sink.OnChange(GUID_COMPARTMENT_KEYBOARD_OPENCLOSE);assert(o.reads==reads);
  if(fault==4)o.failUnadvise=true;
  const bool closed=DisconnectCompartment(sink,r);
  if(fault==5 || fault==7){assert(!closed && r.disconnected && !r.released && o.refs==5);}
  else if(fault==4){assert(!closed && o.refs==5 && o.sink && e.sinkReferences==2);
   assert(!DisconnectCompartment(sink,r) && o.unadvises==1);
   // Fixture-only destruction of its fake source; never a production retry.
   o.sink->Release();o.sink=nullptr;
  }else{assert(closed && !o.refs && !o.sink && e.sinkReferences==1);
   assert(e.referencesAcquired==e.referencesReleased && r.disconnected && r.released);}
 }
 assert(pins==8 && clears>=8);
}
'''
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / 'windows.h').write_text(stub)
            for name in ('msctf.h', 'oleauto.h'):
                (root / name).write_text('#pragma once\n#include "windows.h"\n')
            cpp, exe = root / 'adapter.cpp', root / ('adapter.exe' if os.name == 'nt' else 'adapter')
            cpp.write_text(code)
            built = subprocess.run([compiler, '-std=c++17', '-Wall', '-Wextra', '-Werror',
                                    '-I', str(root), '-I', str(Path(__file__).resolve().parents[1] / 'e2e'),
                                    str(cpp), '-o', str(exe)], capture_output=True, text=True, timeout=30)
            self.assertEqual(built.returncode, 0, built.stdout + built.stderr)
            ran = subprocess.run([str(exe)], capture_output=True, text=True, timeout=5)
            try:
                self.assertEqual(ran.returncode, 0, ran.stdout + ran.stderr)
            finally:
                remove_completed_image(root, exe, ran)
