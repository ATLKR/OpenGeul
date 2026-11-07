"""Reproduce exact public source patch from the cached pinned baseline, no network."""
from pathlib import Path
import difflib
import hashlib
import json

ROOT=Path(__file__).resolve().parents[4]
HERE=ROOT/'suite/engine-build/writer-server-observer-diagnostic'
UPSTREAM=HERE/'tests/upstream'
SOURCES=('winaccessibility/source/UAccCOM/MAccessible.cxx','winaccessibility/source/service/AccObjectWinManager.cxx',
         'winaccessibility/inc/AccObjectWinManager.hxx','winaccessibility/Library_uacccom.mk','winaccessibility/Library_winaccessibility.mk')

def replace_once(text,old,new):
    if text.count(old)!=1:raise ValueError('Pinned source anchor is not unique')
    return text.replace(old,new,1)

def modify():
    for name in SOURCES:
        target=UPSTREAM/name
        if not target.is_file():raise ValueError('Pinned public source fixture is missing')
    before={name:(UPSTREAM/name).read_text() for name in SOURCES};after=dict(before)
    name=SOURCES[0];s=before[name]
    s=replace_once(s,'#include "MAccessible.h"','#include "MAccessible.h"\n#include <opengeul_writer_observer/observer_api.hxx>\nnamespace ow = opengeul::writer_observer;')
    s=replace_once(s,'CMAccessible::~CMAccessible()\n{','CMAccessible::~CMAccessible()\n{\n    ow::invalid_object(static_cast<IMAccessible*>(this));')
    start=s.index('COM_DECLSPEC_NOTHROW STDMETHODIMP CMAccessible::get_accFocus(')
    end=s.index('\n/**',start)
    original=s[start:end]
    getter=original.replace('    SolarMutexGuard g;','    ow::Scope observer(ow::observer_sink(), ow::Kind::Getter, nullptr, static_cast<IMAccessible*>(this), 0, 0);\n    SolarMutexGuard g;\n    observer.mark(ow::Phase::LockAcquired, 0);')
    getter=getter.replace('if (m_isDestroy) return S_FALSE;','if (m_isDestroy) { observer.mark(ow::Phase::Branch, 1); observer.mark(ow::Phase::Return, 1); return S_FALSE; }')
    getter=getter.replace('            return E_INVALIDARG;','            observer.mark(ow::Phase::Branch, 2);\n            observer.mark(ow::Phase::Return, 2);\n            return E_INVALIDARG;')
    getter=getter.replace('            pvarChild->vt = VT_EMPTY;', '            observer.mark(ow::Phase::Branch, 3);\n            pvarChild->vt = VT_EMPTY;')
    getter=getter.replace('            return S_OK;','            observer.mark(ow::Phase::TagWritten, 1);\n            observer.mark(ow::Phase::OutputComplete, 1);\n            observer.mark(ow::Phase::Return, 0);\n            return S_OK;')
    getter=getter.replace('                return E_FAIL;','                observer.mark(ow::Phase::Branch, 4);\n                observer.mark(ow::Phase::Return, 3);\n                return E_FAIL;')
    getter=getter.replace('            pIMAcc->AddRef();','            observer.mark(ow::Phase::Branch, 5);\n            pIMAcc->AddRef();')
    getter=getter.replace('            pvarChild->vt = VT_DISPATCH;','            pvarChild->vt = VT_DISPATCH;\n            observer.mark(ow::Phase::TagWritten, 2);')
    getter=getter.replace('            pvarChild->pdispVal = pIMAcc;','            pvarChild->pdispVal = pIMAcc;\n            observer.mark(ow::Phase::OutputComplete, 2);')
    # Only the final success return has this exact indentation in the pinned getter.
    getter=replace_once(getter,'        return S_OK;\n\n    } catch(...) { return E_FAIL; }','        observer.mark(ow::Phase::Return, 0);\n        return S_OK;\n\n    } catch(...) { observer.mark(ow::Phase::Branch, 6); observer.mark(ow::Phase::Return, 3); return E_FAIL; }')
    s=s[:start]+getter+s[end:]
    start=s.index('COM_DECLSPEC_NOTHROW STDMETHODIMP CMAccessible::Put_XAccFocus(');end=s.index('\n/**',start)
    focus=s[start:end]
    focus=focus.replace('    try {','    const unsigned argument = dChildID == CHILDID_SELF ? 1 : (dChildID == UACC_NO_FOCUS ? 2 : 3);\n    ow::Scope observer(ow::observer_sink(), ow::Kind::Focus, nullptr, static_cast<IMAccessible*>(this), 0, argument);\n    try {',1)
    focus=focus.replace('if (m_isDestroy) return S_FALSE;','if (m_isDestroy) { observer.mark(ow::Phase::Return, 1); return S_FALSE; }')
    focus=focus.replace('                m_pIParent->Put_XAccFocus(m_dChildID);','                observer.mark(ow::Phase::ParentCallBefore, 1);\n                m_pIParent->Put_XAccFocus(m_dChildID);\n                observer.mark(ow::Phase::ParentCallAfter, 1);')
    focus=focus.replace('            m_dFocusChildID = dChildID;','            m_dFocusChildID = dChildID;\n            observer.mark(ow::Phase::Assignment, argument);')
    focus=focus.replace('                m_pIParent->Put_XAccFocus(dChildID);','                observer.mark(ow::Phase::ParentCallBefore, argument);\n                m_pIParent->Put_XAccFocus(dChildID);\n                observer.mark(ow::Phase::ParentCallAfter, argument);')
    focus=focus.replace('        return S_OK;','        observer.mark(ow::Phase::Return, 0);\n        return S_OK;')
    focus=focus.replace('} catch(...) { return E_FAIL; }','} catch(...) { observer.mark(ow::Phase::Return, 3); return E_FAIL; }')
    s=s[:start]+focus+s[end:]
    s=replace_once(s,'    g_pAccObjectManager = reinterpret_cast<AccObjectWinManager*>(pManager);','    g_pAccObjectManager = reinterpret_cast<AccObjectWinManager*>(pManager);\n    if (g_pAccObjectManager && !g_pAccObjectManager->ObserverInstall(ow::observer_sink()))\n        ow::invalid_manager(ow::observer_sink(), g_pAccObjectManager);')
    s=replace_once(s,'    m_isDestroy = true;','    ow::invalid_object(static_cast<IMAccessible*>(this));\n    m_isDestroy = true;')
    after[name]=s
    name=SOURCES[1];s=before[name]
    s=replace_once(s,'#include <AccObjectWinManager.hxx>','#include <AccObjectWinManager.hxx>\n#include <opengeul_writer_observer/observer_api.hxx>\nnamespace ow = opengeul::writer_observer;')
    s=replace_once(s,'AccObjectWinManager::~AccObjectWinManager()\n{','AccObjectWinManager::~AccObjectWinManager()\n{\n    ow::invalid_manager(ObserverSink(), this);')
    s=replace_once(s,'    IMAccessible* pRetIMAcc = nullptr;','    ow::Route observer(ObserverSink(), this, static_cast<std::uintptr_t>(nHWnd), lParam == OBJID_CLIENT);\n    IMAccessible* pRetIMAcc = nullptr;')
    s=replace_once(s,'GetTopWindowIMAccessible(hWnd);','GetTopWindowIMAccessible(hWnd, observer.ready());')
    s=replace_once(s,'        LRESULT result = LresultFromObject(IID_IAccessible, wParam, pRetIMAcc);','        observer.enter(pRetIMAcc);\n        LRESULT result = LresultFromObject(IID_IAccessible, wParam, pRetIMAcc);\n        observer.result(result > 0 ? 1 : (result == 0 ? 2 : 3));')
    s=replace_once(s,'GetTopWindowIMAccessible(HWND hWnd)','GetTopWindowIMAccessible(HWND hWnd, bool observerReady)')
    s=replace_once(s,'    pRet->AddRef();\n    return pRet;','    pRet->AddRef();\n    if (observerReady)\n        ow::bind_root(ObserverSink(), this, pRet, reinterpret_cast<std::uintptr_t>(hWnd));\n    return pRet;')
    s=replace_once(s,'    if (iter != HwndXAcc.end())\n        HwndXAcc.erase(iter);','    if (iter != HwndXAcc.end())\n    {\n        ow::invalid_map(ObserverSink(), this, reinterpret_cast<std::uintptr_t>(iter->first), 2);\n        HwndXAcc.erase(iter);\n    }')
    s=replace_once(s,'    HwndXAcc.emplace(hWnd,pXAcc);','    ow::invalid_map(ObserverSink(), this, reinterpret_cast<std::uintptr_t>(hWnd), 3);\n    HwndXAcc.emplace(hWnd,pXAcc);')
    after[name]=s
    name=SOURCES[2];s=before[name]
    s=replace_once(s,'#include <mutex>','#include <mutex>\n#include <opengeul_writer_observer/private_sink.hxx>')
    s=replace_once(s,'private:\n    typedef std::map','private:\n    std::atomic<opengeul::writer_observer::Sink> m_observerSink{nullptr};\n    typedef std::map')
    s=replace_once(s,'    IMAccessible* GetTopWindowIMAccessible(HWND hWnd);','    IMAccessible* GetTopWindowIMAccessible(HWND hWnd, bool observerReady);')
    s=replace_once(s,'public:\n    AccObjectWinManager();','public:\n    bool ObserverInstall(opengeul::writer_observer::Sink sink) noexcept\n    {\n        auto expected = static_cast<opengeul::writer_observer::Sink>(nullptr);\n        return m_observerSink.compare_exchange_strong(expected, sink, std::memory_order_acq_rel) || expected == sink;\n    }\n    opengeul::writer_observer::Sink ObserverSink() const noexcept\n    { return m_observerSink.load(std::memory_order_acquire); }\n    AccObjectWinManager();')
    after[name]=s
    for name,library in [(SOURCES[3],'UAccCOM'),(SOURCES[4],'winaccessibility')]:
        s=before[name];s=replace_once(s,f'$(eval $(call gb_Library_Library,{library}))',f'$(eval $(call gb_Library_Library,{library}))\n\n$(eval $(call gb_Library_add_defs,{library},-DOPENGEUL_WRITER_SERVER_OBSERVER_DIAGNOSTIC))')
        if library=='UAccCOM':s=replace_once(s,'\twinaccessibility/source/UAccCOM/MAccessible \\\n','\twinaccessibility/source/UAccCOM/MAccessible \\\n\twinaccessibility/source/UAccCOM/OpenGeulWriterObserver \\\n')
        after[name]=s
    patch=''.join(''.join(difflib.unified_diff(before[n].splitlines(True),after[n].splitlines(True),fromfile='a/'+n,tofile='b/'+n,n=3)) for n in SOURCES)
    (HERE/'source.patch').write_text(patch)
    for n in SOURCES:
        p=ROOT/'review/patched-source'/n;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(after[n])
    return before,after

if __name__=='__main__':modify()
