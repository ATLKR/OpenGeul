#pragma once
#include <windows.h>
#include <msctf.h>
#include <oleauto.h>
#include "ime_compartment_protocol.h"

namespace opengeul_ime {
// Construct once in module-owned storage. Never destroy while a subscription
// may exist. Pin() precedes Advise, and the pin intentionally lasts until the
// retained engine exits, even after a proved unsubscribe. There is no destructor
// that releases interfaces from an arbitrary thread or after an expired budget.
template<class Host>
class OwnedCompartmentSink final : public ITfCompartmentEventSink {
    Host& host;
    CompartmentLeaseRecord& lease;
    CompartmentApiReceipt& receipt;
    ITfThreadMgr* manager=nullptr;
    ITfCompartmentMgr* compartments=nullptr;
    IEnumGUID* enumeration=nullptr;
    ITfCompartment* open=nullptr;
    ITfSource* source=nullptr;
    DWORD cookie=TF_INVALID_COOKIE;
    // A failed VariantClear leaves ownership here until engine exit, never in
    // a discarded stack local. Each of these two values is read at most once.
    VARIANT baselineValue{},callbackValue{};
    static void ModuleAnchor() {}
    static uint32_t Load(uint32_t& value) {
        return static_cast<uint32_t>(InterlockedCompareExchange(reinterpret_cast<volatile LONG*>(&value),0,0));
    }
    template<class T> void Acquired(T* value) {if(value)++receipt.referencesAcquired;}
    bool Read(int32_t expected,bool callback,CompartmentRead& row) {
        const auto boundary=[&](){return callback?host.CallbackBoundary():Check();};
        if(!open || row.attempts || !boundary())return false;
        row.attempts=1;
        VARIANT& value=callback?callbackValue:baselineValue;VariantInit(&value);
        try {row.hr=open->GetValue(&value);}
        catch(...) {receipt.apiException=receipt.variantCleanupFailed=1;throw;}
        const bool returnedInBudget=boundary();
        row.type=value.vt;
        const bool matched=row.hr==S_OK && value.vt==VT_I4 && value.lVal==expected;
        // Always discharge an owned VARIANT, including a failed/late getter.
        // Its cleanup cannot turn an expired observation into success.
        row.clearHr=VariantClear(&value);
        if(row.clearHr!=S_OK)receipt.variantCleanupFailed=1;
        row.matched=matched && row.clearHr==S_OK && returnedInBudget && boundary()?1:0;
        return row.matched!=0;
    }
    template<class T> bool ReleaseOne(T*& value) {
        if(!value)return true;
        if(!Check())return false;
        T* held=value;value=nullptr;held->Release();++receipt.referencesReleased;
        return Check();
    }
public:
    OwnedCompartmentSink(Host& host,CompartmentLeaseRecord& lease,CompartmentApiReceipt& receipt)
        : host(host),lease(lease),receipt(receipt) {}
    HRESULT STDMETHODCALLTYPE QueryInterface(REFIID iid,void** output) override {
        if(!output)return E_POINTER;
        *output=nullptr;
        if(!IsEqualIID(iid,IID_IUnknown) && !IsEqualIID(iid,__uuidof(ITfCompartmentEventSink)))return E_NOINTERFACE;
        *output=static_cast<ITfCompartmentEventSink*>(this);AddRef();return S_OK;
    }
    ULONG STDMETHODCALLTYPE AddRef() override {
        return static_cast<ULONG>(InterlockedIncrement(reinterpret_cast<volatile LONG*>(&receipt.sinkReferences)));
    }
    ULONG STDMETHODCALLTYPE Release() override {
        const LONG count=InterlockedDecrement(reinterpret_cast<volatile LONG*>(&receipt.sinkReferences));
        if(count<1)InterlockedExchange(reinterpret_cast<volatile LONG*>(&receipt.badSinkReference),1);
        // One module-owned reference is deliberately retained through engine exit.
        return count>0?static_cast<ULONG>(count):0;
    }
    HRESULT STDMETHODCALLTYPE OnChange(REFGUID guid) override {
        InterlockedIncrement(reinterpret_cast<volatile LONG*>(&lease.activeCallbacks));
        struct Leave {
            CompartmentLeaseRecord& r;
            ~Leave(){InterlockedDecrement(reinterpret_cast<volatile LONG*>(&r.activeCallbacks));}
        } leave{lease};
        try {
            if(!IsEqualGUID(guid,GUID_COMPARTMENT_KEYBOARD_OPENCLOSE))return S_OK;
            if(!host.SameCallbackThread()) {host.RejectForeignCallback();return S_OK;}
            if(host.ClaimCallback() && Read(0,true,receipt.callback) && host.CallbackBoundary())
                host.CaptureCallback();
        } catch(...) {
            InterlockedExchange(reinterpret_cast<volatile LONG*>(&receipt.callbackException),1);
            static_assert(noexcept(host.RejectCallbackException()));
            host.RejectCallbackException();
        }
        return S_OK;
    }
    bool Check() {return host.CommandBoundary();}
    uint32_t ActiveCallbacks() {return Load(lease.activeCallbacks);}
    bool CallbacksIdle(const CompartmentLeaseRecord& r) {return &r==&lease && ActiveCallbacks()==0;}
    bool Pin() {
        HMODULE module=nullptr;
        return GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS|GET_MODULE_HANDLE_EX_FLAG_PIN,
            reinterpret_cast<LPCWSTR>(&ModuleAnchor),&module)!=0 && module!=nullptr;
    }
    bool AcquireExistingSource() {
        if(!Check())return false;
        const auto module=GetModuleHandleW(L"msctf.dll");
        if(!Check() || !module)return false;
        using ExistingManager=HRESULT (WINAPI*)(ITfThreadMgr**);
        const auto get=reinterpret_cast<ExistingManager>(GetProcAddress(module,"TF_GetThreadMgr"));
        if(!Check() || !get)return false;
        receipt.managerHr=get(&manager);Acquired(manager);
        if(!Check() || receipt.managerHr!=S_OK || !manager)return false;
        receipt.managerInterfaceHr=manager->QueryInterface(__uuidof(ITfCompartmentMgr),reinterpret_cast<void**>(&compartments));
        Acquired(compartments);
        if(!Check() || receipt.managerInterfaceHr!=S_OK || !compartments)return false;
        receipt.enumerationHr=compartments->EnumCompartments(&enumeration);Acquired(enumeration);
        if(!Check() || receipt.enumerationHr!=S_OK || !enumeration)return false;
        bool found=false;
        for(unsigned i=0;i<64 && !found;++i) {
            if(!Check())return false;
            GUID guid{};ULONG fetched=0;
            receipt.nextHr=enumeration->Next(1,&guid,&fetched);++receipt.enumerationCount;
            if(!Check() || receipt.nextHr!=S_OK || fetched!=1)return false;
            found=IsEqualGUID(guid,GUID_COMPARTMENT_KEYBOARD_OPENCLOSE)!=0;
        }
        if(!found || !Check())return false;
        // GetCompartment is used only after enumeration proved it already exists.
        receipt.compartmentHr=compartments->GetCompartment(GUID_COMPARTMENT_KEYBOARD_OPENCLOSE,&open);Acquired(open);
        if(!Check() || receipt.compartmentHr!=S_OK || !open)return false;
        receipt.sourceHr=open->QueryInterface(__uuidof(ITfSource),reinterpret_cast<void**>(&source));Acquired(source);
        return Check() && receipt.sourceHr==S_OK && source!=nullptr;
    }
    bool Advise() {
        if(!source || !Check())return false;
        receipt.adviseHr=source->AdviseSink(__uuidof(ITfCompartmentEventSink),
            static_cast<ITfCompartmentEventSink*>(this),&cookie);
        receipt.invalidCookie=cookie==TF_INVALID_COOKIE?1:0;
        return receipt.adviseHr==S_OK && !receipt.invalidCookie;
    }
    bool SubscriptionPossible() const {return receipt.adviseHr==S_OK || cookie!=TF_INVALID_COOKIE;}
    bool ReadOpenOne() {return Read(1,false,receipt.baseline);}
    bool Unadvise() {
        if(!source || cookie==TF_INVALID_COOKIE || !Check())return false;
        receipt.unadviseHr=source->UnadviseSink(cookie);
        if(receipt.unadviseHr!=S_OK)return false;
        cookie=TF_INVALID_COOKIE;
        return Load(receipt.sinkReferences)==1 && !Load(receipt.badSinkReference);
    }
    bool ReleaseOwned() {
        if(Load(receipt.sinkReferences)!=1 || Load(receipt.badSinkReference)
            || receipt.variantCleanupFailed || receipt.apiException || Load(receipt.callbackException))return false;
        return ReleaseOne(source) && ReleaseOne(open) && ReleaseOne(enumeration)
            && ReleaseOne(compartments) && ReleaseOne(manager)
            && receipt.referencesAcquired==receipt.referencesReleased
            && Load(receipt.sinkReferences)==1 && !Load(receipt.badSinkReference);
    }
};
}
