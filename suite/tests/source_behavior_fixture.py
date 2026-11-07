"""Compile original and actually installed methods with a small SDK-free boundary."""
from pathlib import Path
from writer_server_compile_support import compiled_fixture
import tempfile


def method(text, signature):
    start=text.index(signature)
    brace=text.index('{',start);depth=1;end=brace+1
    while depth:
        if text[end]=='{':depth+=1
        if text[end]=='}':depth-=1
        end+=1
    return text[start:end]


def exercise_patched_source(case, tree, upstream):
    relative='winaccessibility/source/UAccCOM/MAccessible.cxx'
    before=(upstream/relative).read_text();after=(tree/relative).read_text()
    functions=[]
    for source,name in [(before,'Original'),(after,'Observed')]:
        for method_name in ('get_accFocus','Put_XAccFocus'):
            functions.append(method(source,'COM_DECLSPEC_NOTHROW STDMETHODIMP CMAccessible::'+method_name).replace('CMAccessible::',name+'::'))
    manager='winaccessibility/source/service/AccObjectWinManager.cxx'
    for source,name in [((upstream/manager).read_text(),'OriginalManager'),((tree/manager).read_text(),'ObservedManager')]:
        functions.append(method(source,'void AccObjectWinManager::UpdateAccFocus(').replace('AccObjectWinManager::',name+'::'))
    preamble=r'''
#include <cassert>
#include <stdexcept>
#include <vector>
#include "wire.h"
#define COM_DECLSPEC_NOTHROW
#define STDMETHODIMP int
constexpr int S_OK=0,S_FALSE=1,E_INVALIDARG=2,E_FAIL=3,VT_EMPTY=0,VT_DISPATCH=9,CHILDID_SELF=0,UACC_NO_FOCUS=-2;
struct IMAccessible {virtual int Put_XAccFocus(long)=0;virtual void AddRef(){};virtual ~IMAccessible()=default;};
struct Variant {int vt=7;IMAccessible* pdispVal=nullptr;};using VARIANT=Variant;
bool locked=false;Variant* output=nullptr;int addrefs=0;bool throwing=false;std::vector<long> calls;
struct Target:IMAccessible {int Put_XAccFocus(long n)override{calls.push_back(n);if(throwing)throw std::runtime_error("synthetic");return 0;}void AddRef()override{++addrefs;}}target;
struct Lookup {bool missing=false;IMAccessible* GetIAccessibleFromResID(long){if(throwing)throw std::runtime_error("synthetic");return missing?nullptr:&target;}}lookup;
Lookup* g_pAccObjectManager=&lookup;
struct SolarMutexGuard {SolarMutexGuard(){assert(!locked);locked=true;}~SolarMutexGuard(){locked=false;}};
namespace opengeul::writer_observer {
inline int observer_sink(){return 0;}
struct Scope {
    Kind kind;
    Scope(int,Kind k,void*,IMAccessible*,std::uintptr_t,unsigned):kind(k){if(k==Kind::Getter)assert(!locked);}
    void mark(Phase p,unsigned d){
        if(kind!=Kind::Getter)return;
        if(p==Phase::LockAcquired)assert(locked);
        if(p==Phase::TagWritten){assert(output);assert(output->vt==(d==1?VT_EMPTY:VT_DISPATCH));}
        if(p==Phase::OutputComplete){assert(output);assert(output->vt==(d==1?VT_EMPTY:VT_DISPATCH));if(d==2)assert(output->pdispVal==&target);}
    }
};}
namespace ow=opengeul::writer_observer;
struct Original:IMAccessible {bool m_isDestroy=false;long m_dFocusChildID=UACC_NO_FOCUS,m_dChildID=41;IMAccessible* m_pIParent=nullptr;
 int get_accFocus(Variant*);int Put_XAccFocus(long)override;};
struct Observed:IMAccessible {bool m_isDestroy=false;long m_dFocusChildID=UACC_NO_FOCUS,m_dChildID=41;IMAccessible* m_pIParent=nullptr;
 int get_accFocus(Variant*);int Put_XAccFocus(long)override;};
struct XAccessible{int id;};std::vector<int> focusOrder;
struct AccObject {int id;void unsetFocus(){focusOrder.push_back(-id);}void setFocus(){focusOrder.push_back(id);}};
struct OriginalManager {XAccessible* oldFocus;AccObject a{1},b{2};AccObject* GetAccObjByXAcc(XAccessible* p){return p?(p->id==1?&a:&b):nullptr;}void UpdateAccFocus(XAccessible*);};
struct ObservedManager {XAccessible* oldFocus;AccObject a{1},b{2};AccObject* GetAccObjByXAcc(XAccessible* p){return p?(p->id==1?&a:&b):nullptr;}void UpdateAccFocus(XAccessible*);};
'''
    main=r'''
int main(){
 for(int scenario=0;scenario<6;++scenario){
  Original a;Observed b;a.m_isDestroy=b.m_isDestroy=scenario==0;
  a.m_dFocusChildID=b.m_dFocusChildID=scenario==2?UACC_NO_FOCUS:17;
  lookup.missing=scenario==3;throwing=scenario==5;
  Variant x,y;output=&x;addrefs=0;auto ra=a.get_accFocus(scenario==1?nullptr:&x);auto refs=addrefs;
  output=&y;addrefs=0;auto rb=b.get_accFocus(scenario==1?nullptr:&y);
  assert(ra==rb&&x.vt==y.vt&&x.pdispVal==y.pdispVal&&refs==addrefs);
  int expected[]={S_FALSE,E_INVALIDARG,S_OK,E_FAIL,S_OK,E_FAIL};assert(rb==expected[scenario]);
 }
 for(long argument:{0L,-2L,7L})for(bool fail:{false,true}){
  Original a;Observed b;a.m_pIParent=b.m_pIParent=&target;throwing=fail;calls.clear();
  auto ra=a.Put_XAccFocus(argument);auto originalCalls=calls;calls.clear();auto rb=b.Put_XAccFocus(argument);
  assert(ra==rb&&a.m_dFocusChildID==b.m_dFocusChildID&&calls==originalCalls);
  assert(calls.size()==1&&calls[0]==(argument==0?41:argument));
 }
 XAccessible old{1},next{2};OriginalManager a;a.oldFocus=&old;ObservedManager b;b.oldFocus=&old;
 focusOrder.clear();a.UpdateAccFocus(&next);auto expected=focusOrder;focusOrder.clear();b.UpdateAccFocus(&next);
 assert((expected==std::vector<int>{-1,2})&&focusOrder==expected);
 focusOrder.clear();b.UpdateAccFocus(&next);assert((focusOrder==std::vector<int>{2}));
}
'''
    with tempfile.TemporaryDirectory() as temp:
        cpp=Path(temp)/'source.cpp';binary=Path(temp)/'source'
        cpp.write_text(preamble+'\n'.join(functions)+main)
        backend=Path(__file__).resolve().parents[1]/'engine-build/writer-server-observer-diagnostic'
        with compiled_fixture(case,cpp,includes=[backend]) as image:
            result=image.run();case.assertEqual(result.returncode,0,result.stderr)


def exercise_private_header(case, tree):
    header=(tree/'winaccessibility/inc/AccObjectWinManager.hxx').read_text()
    header='\n'.join(line for line in header.splitlines() if not line.lstrip().startswith(('#include','#pragma once')))
    before=r'''
#include "private_sink.hxx"
#include <map>
#include <mutex>
#include <type_traits>
using HWND=void*;using WPARAM=std::uintptr_t;using sal_Int64=std::int64_t;
namespace css {namespace accessibility{class XAccessible{};}namespace uno{struct Any{};}}
namespace rtl {template<class T>struct Reference{};}
struct IMAccessible{};class ResIDGenerator{};class AccObject{};
'''
    after=r'''
AccObjectWinManager::AccObjectWinManager():oldFocus(nullptr){}
AccObjectWinManager::~AccObjectWinManager(){}
bool AccObjectWinManager::InsertAccObj(css::accessibility::XAccessible*,css::accessibility::XAccessible*,HWND){return false;}
IMAccessible* AccObjectWinManager::GetIAccessibleFromXAccessible(css::accessibility::XAccessible*){return nullptr;}
IMAccessible* AccObjectWinManager::GetIAccessibleFromResID(long){return nullptr;}
using namespace opengeul::writer_observer;
std::uint32_t first(SinkRequest const*,SinkReply* r)noexcept{r->status=4;return 4;}
std::uint32_t second(SinkRequest const*,SinkReply*)noexcept{return 0;}
static_assert(std::is_same_v<decltype(&AccObjectWinManager::ObserverInstall),bool(AccObjectWinManager::*)(Sink)noexcept>);
static_assert(std::is_same_v<decltype(&AccObjectWinManager::ObserverSink),Sink(AccObjectWinManager::*)()const noexcept>);
int main(){AccObjectWinManager manager;if(!manager.ObserverInstall(first)||!manager.ObserverInstall(first)||manager.ObserverInstall(second))return 1;
 SinkReply reply{};if(manager.ObserverSink()(nullptr,&reply)!=4||reply.status!=4)return 2;}
'''
    with tempfile.TemporaryDirectory() as temp:
        cpp=Path(temp)/'header.cpp';binary=Path(temp)/'header';cpp.write_text(before+header+after)
        backend=Path(__file__).resolve().parents[1]/'engine-build/writer-server-observer-diagnostic'
        with compiled_fixture(case,cpp,includes=[backend]) as image:
            result=image.run();case.assertEqual(result.returncode,0,result.stderr)


def exercise_route_methods(case,tree,upstream):
    relative='winaccessibility/source/service/AccObjectWinManager.cxx';functions=[]
    for source,name in [((upstream/relative).read_text(),'Original'),((tree/relative).read_text(),'Observed')]:
        functions.append('sal_Int64\n'+method(source,'AccObjectWinManager::Get_ToATInterface(').replace('AccObjectWinManager::',name+'::'))
        functions.append(method(source,'IMAccessible * AccObjectWinManager::GetTopWindowIMAccessible(').replace('AccObjectWinManager::',name+'::'))
    preamble=r'''
#include <cassert>
#include <cstdint>
#include <map>
#include <mutex>
using sal_Int64=std::int64_t;using HWND=void*;using WPARAM=std::uintptr_t;using LRESULT=std::intptr_t;
constexpr long OBJID_CLIENT=-4;constexpr int IID_IAccessible=1;
int lockDepth=0,addrefs=0,releases=0,binding=0,apiCalls=0;bool missing=false,nullPeer=false;LRESULT supplied=0;
struct Mutex{void lock(){++lockDepth;}void unlock(){--lockDepth;}};
struct IMAccessible{void AddRef(){++addrefs;}void Release(){++releases;}}peer;
struct XAccessible{}accessible;
struct AccObject{IMAccessible* GetIMAccessible(){return nullPeer?nullptr:&peer;}}object;
LRESULT LresultFromObject(int,WPARAM parameter,IMAccessible* p){assert(parameter==13&&p==&peer&&addrefs==1);++apiCalls;return supplied;}
namespace opengeul::writer_observer {
struct Route{bool client;Route(int,void*,std::uintptr_t,bool c):client(c){assert(lockDepth==0);}bool ready(){return client;}
 void enter(IMAccessible* p){assert(p==&peer&&addrefs==1&&lockDepth==0);}
 void result(unsigned d){assert(d==(supplied>0?1u:supplied==0?2u:3u));}};
void bind_root(int,void*,IMAccessible* p,std::uintptr_t hwnd){assert(p==&peer&&hwnd==99&&addrefs==1&&lockDepth==1);++binding;}
}
namespace ow=opengeul::writer_observer;
struct Original {using XHWNDToXAccHash=std::map<HWND,XAccessible*>;Mutex m_Mutex;XHWNDToXAccHash HwndXAcc;
 AccObject* GetAccObjByXAcc(XAccessible*){return missing?nullptr:&object;}sal_Int64 Get_ToATInterface(sal_Int64,long,WPARAM);IMAccessible* GetTopWindowIMAccessible(HWND);};
struct Observed {using XHWNDToXAccHash=std::map<HWND,XAccessible*>;Mutex m_Mutex;XHWNDToXAccHash HwndXAcc;
 int ObserverSink(){return 0;}AccObject* GetAccObjByXAcc(XAccessible*){return missing?nullptr:&object;}
 sal_Int64 Get_ToATInterface(sal_Int64,long,WPARAM);IMAccessible* GetTopWindowIMAccessible(HWND,bool);};
'''
    main=r'''
int main(){for(int condition=0;condition<5;++condition)for(LRESULT result:{-1,0,1}){
 Original a;Observed b;if(condition!=1){a.HwndXAcc[reinterpret_cast<void*>(99)]=&accessible;b.HwndXAcc=a.HwndXAcc;}
 missing=condition==2;nullPeer=condition==3;supplied=result;long param=condition==4?0:OBJID_CLIENT;
 addrefs=releases=apiCalls=0;auto expected=a.Get_ToATInterface(99,param,13);int refs=addrefs,rel=releases,apis=apiCalls;
 addrefs=releases=apiCalls=binding=0;auto actual=b.Get_ToATInterface(99,param,13);
 assert(actual==expected&&refs==addrefs&&rel==releases&&apis==apiCalls&&lockDepth==0);
 assert(binding==(condition==0?1:0));if(condition==0)assert(actual==result&&addrefs==1&&releases==1&&apiCalls==1);
}}
'''
    with tempfile.TemporaryDirectory() as temp:
        cpp=Path(temp)/'route.cpp';binary=Path(temp)/'route';cpp.write_text(preamble+'\n'.join(functions)+main)
        with compiled_fixture(case,cpp) as image:
            result=image.run();case.assertEqual(result.returncode,0,result.stderr)


def exercise_map_deletion(case,tree,upstream):
    relative='winaccessibility/source/service/AccObjectWinManager.cxx';functions=[]
    for source,name in [((upstream/relative).read_text(),'Original'),((tree/relative).read_text(),'Observed')]:
        functions.append(method(source,'void AccObjectWinManager::DeleteFromHwndXAcc(').replace('AccObjectWinManager::',name+'::'))
    preamble=r'''
#include <algorithm>
#include <cassert>
#include <cstdint>
#include <cstdlib>
#include <iostream>
#include <map>
#include <mutex>
using HWND=void*;struct XAccessible{}a,b;unsigned invalidations=0;
struct CheckedMap:std::map<HWND,XAccessible*>{void erase(iterator it){if(it==end())std::exit(71);std::map<HWND,XAccessible*>::erase(it);}};
namespace opengeul::writer_observer {void invalid_map(int,void*,std::uintptr_t,unsigned reason){assert(reason==2);++invalidations;}}
namespace ow=opengeul::writer_observer;
struct Original {using XHWNDToXAccHash=CheckedMap;std::recursive_mutex m_Mutex;CheckedMap HwndXAcc;void DeleteFromHwndXAcc(XAccessible const*);};
struct Observed {using XHWNDToXAccHash=CheckedMap;std::recursive_mutex m_Mutex;CheckedMap HwndXAcc;int ObserverSink(){return 0;}void DeleteFromHwndXAcc(XAccessible const*);};
'''
    main=r'''
int main(){int mode=0;std::cin>>mode;bool found=mode==1;Original x;Observed y;
 x.HwndXAcc[reinterpret_cast<void*>(99)]=&a;y.HwndXAcc=x.HwndXAcc;
 x.DeleteFromHwndXAcc(found?&a:&b);y.DeleteFromHwndXAcc(found?&a:&b);
 assert(x.HwndXAcc==y.HwndXAcc&&invalidations==(found?1u:0u));
 assert(y.HwndXAcc.size()==(found?0u:1u));}
'''
    with tempfile.TemporaryDirectory() as temp:
        cpp=Path(temp)/'delete.cpp';binary=Path(temp)/'delete';cpp.write_text(preamble+'\n'.join(functions)+main)
        with compiled_fixture(case,cpp,extra_flags=['-Wno-misleading-indentation']) as image:
            for found in (1,0):
                result=image.run(input=str(found))
                case.assertEqual(result.returncode,0,'actual installed DeleteFromHwndXAcc attempted erase(end)' if not found else result.stderr)
