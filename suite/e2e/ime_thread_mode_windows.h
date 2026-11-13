#pragma once
#include <windows.h>
#include <msctf.h>
#include <oleauto.h>
#include "ime_thread_mode.h"

namespace opengeul_ime {
// No new manager, activation, global compartment or absent-compartment fallback.
class WindowsThreadMode {
    ModeReceipt& receipt;
    uint64_t deadline, frequency;
    ITfThreadMgr* manager=nullptr;
    ITfCompartmentMgr* compartments=nullptr;
    IEnumGUID* enumeration=nullptr;
    ITfCompartment* open=nullptr;
    ITfCompartment* conversion=nullptr;
    ITfClientId* client=nullptr;
    uint32_t acquired=0, released=0;
    ULONG fetched=0;
public:
    WindowsThreadMode(ModeReceipt& receipt, uint64_t deadline, uint64_t frequency)
        : receipt(receipt), deadline(deadline), frequency(frequency) {}
    bool WithinBudget() {
        LARGE_INTEGER now={}, actual={};
        return deadline>0 && frequency>0 && QueryPerformanceFrequency(&actual)
            && uint64_t(actual.QuadPart)==frequency && QueryPerformanceCounter(&now)
            && now.QuadPart>0 && uint64_t(now.QuadPart)<deadline;
    }
    int32_t ExistingManager() {
        // An existing TSF manager already requires its system module to be loaded.
        // GetModuleHandle does not create a manager or acquire a library reference.
        const auto module=GetModuleHandleW(L"msctf.dll");
        receipt.modulePresent=module!=nullptr;
        if (!module) return NotAttempted;
        using GetThreadManager=HRESULT (WINAPI*)(ITfThreadMgr**);
        const auto get=reinterpret_cast<GetThreadManager>(GetProcAddress(module,"TF_GetThreadMgr"));
        receipt.lookupPresent=get!=nullptr;
        if (!get) return NotAttempted;
        ++receipt.managerCallAttempts;
        const auto hr=get(&manager); if (manager) ++acquired; return hr;
    }
    bool HasManager() const { return manager!=nullptr; }
    int32_t CompartmentManager() {
        const auto hr=manager->QueryInterface(__uuidof(ITfCompartmentMgr),reinterpret_cast<void**>(&compartments));
        if (compartments) ++acquired;
        return hr;
    }
    bool HasCompartmentManager() const { return compartments!=nullptr; }
    int32_t BeginEnumeration() {
        const auto hr=compartments->EnumCompartments(&enumeration);
        if (enumeration) ++acquired;
        return hr;
    }
    bool HasEnumerator() const { return enumeration!=nullptr; }
    int32_t Next(int& key) {
        GUID guid={}; fetched=0;
        const auto hr=enumeration->Next(1,&guid,&fetched);
        if (hr!=S_OK || fetched!=1) return hr;
        key=IsEqualGUID(guid,GUID_COMPARTMENT_KEYBOARD_OPENCLOSE) ? 1 :
            IsEqualGUID(guid,GUID_COMPARTMENT_KEYBOARD_INPUTMODE_CONVERSION) ? 2 : 0;
        return S_OK;
    }
    uint32_t Fetched() const { return fetched; }
    int32_t Get(int key) {
        auto& target=key==1 ? open : conversion;
        const auto hr=compartments->GetCompartment(key==1 ? GUID_COMPARTMENT_KEYBOARD_OPENCLOSE :
            GUID_COMPARTMENT_KEYBOARD_INPUTMODE_CONVERSION,&target);
        if (target) ++acquired;
        return hr;
    }
    bool HasCompartment(int key) const { return (key==1 ? open : conversion)!=nullptr; }
    Value Read(int key) {
        VARIANT value; VariantInit(&value);
        const auto hr=(key==1 ? open : conversion)->GetValue(&value);
        const Value result{static_cast<int32_t>(hr),value.vt,
            value.vt==VT_I4 ? static_cast<int32_t>(value.lVal) : 0};
        const auto clear=VariantClear(&value);
        if (receipt.variantClearHr==NotAttempted || clear!=S_OK) receipt.variantClearHr=clear;
        if (clear!=S_OK) {
            if (!receipt.cleanupStatus) receipt.cleanupStatus=clear;
        }
        return result;
    }
    int32_t ClientInterface() {
        const auto hr=manager->QueryInterface(__uuidof(ITfClientId),reinterpret_cast<void**>(&client));
        if (client) ++acquired;
        return hr;
    }
    bool HasClient() const { return client!=nullptr; }
    int32_t ObserverClient(uint32_t& id) {
        // The removable E2E observer's own identity; never borrow the app or IME ID.
        static const CLSID observer={0x9a60c08c,0xc9e4,0x4d70,{0x90,0xb6,0x2a,0x07,0x3c,0x5b,0xfa,0xd8}};
        TfClientId actual=0; const auto hr=client->GetClientId(observer,&actual); id=actual; return hr;
    }
    int32_t Write(int key,uint32_t id,int32_t requested) {
        VARIANT value; VariantInit(&value); value.vt=VT_I4; value.lVal=requested;
        // A stack VT_I4 has no owned allocation. There is no IMM fallback.
        return (key==1 ? open : conversion)->SetValue(id,&value);
    }
    ReleaseCounts Release() {
        if (client) {client->Release();client=nullptr;++released;}
        if (conversion) {conversion->Release();conversion=nullptr;++released;}
        if (open) {open->Release();open=nullptr;++released;}
        if (enumeration) {enumeration->Release();enumeration=nullptr;++released;}
        if (compartments) {compartments->Release();compartments=nullptr;++released;}
        if (manager) {manager->Release();manager=nullptr;++released;}
        return {acquired,released};
    }
};
} // namespace opengeul_ime
