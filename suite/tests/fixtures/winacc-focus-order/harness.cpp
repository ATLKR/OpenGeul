// Portable semantic harness. No Windows ABI, UNO, COM transport or real mutex.
// All tested focus/cache/state method bodies live in extracted_methods.inc.
#include <cassert>
#include <cstdint>
#include <iostream>
#include <map>
#include <string_view>
#include "compile_constants.hpp"

using HRESULT = std::int32_t;
using DWORD = std::uint32_t;
using sal_Int64 = std::int64_t;
constexpr HRESULT S_OK=0, S_FALSE=1;
constexpr HRESULT E_FAIL=static_cast<HRESULT>(0x80004005u);
constexpr HRESULT E_INVALIDARG=static_cast<HRESULT>(0x80070057u);
constexpr long CHILDID_SELF=0;
constexpr long UACC_NO_FOCUS=0xffff;
constexpr std::uint16_t VT_EMPTY=0, VT_DISPATCH=9;
constexpr DWORD MSAA_NO_STATE=0;
#define COM_DECLSPEC_NOTHROW
#define STDMETHODIMP HRESULT

struct SolarMutexGuard { SolarMutexGuard() {} ~SolarMutexGuard() {} };
struct XAccessible { std::uint32_t synthetic_id; };
class CMAccessible;
using IMAccessible=CMAccessible;
class AccObjectWinManager;
struct VARIANT { std::uint16_t vt=VT_EMPTY; IMAccessible* pdispVal=nullptr; };

class CMAccessible {
public:
    // Test-owned fields use the pinned constructor's relevant initial values.
    bool m_isDestroy=false;
    long m_dFocusChildID=UACC_NO_FOCUS;
    long m_dChildID=0;
    IMAccessible* m_pIParent=nullptr;
    DWORD m_dState=0;
    std::uint32_t refs=1;
    static AccObjectWinManager* g_pAccObjectManager;
    HRESULT Put_XAccFocus(long);
    HRESULT get_accFocus(VARIANT*);
    HRESULT IncreaseState(DWORD);
    HRESULT DecreaseState(DWORD);
    std::uint32_t AddRef() { return ++refs; }
    std::uint32_t Release() { assert(refs>1); return --refs; }
};

struct SyntheticContext {
    bool is() const { return true; }
    const SyntheticContext* operator->() const { return this; }
    sal_Int64 getAccessibleStateSet() const { return 0; } // unexercised EXPANDABLE branch only
};

class AccObject {
public:
    IMAccessible* m_pIMAcc;
    AccObject* m_pParentObj;
    short m_accRole=0;
    SyntheticContext m_xAccContextRef;
    AccObject(IMAccessible* accessible, AccObject* parent):m_pIMAcc(accessible),m_pParentObj(parent) {}
    void setFocus();
    void unsetFocus();
    void IncreaseState(sal_Int64);
    void DecreaseState(sal_Int64);
    DWORD GetMSAAStateFromUNO(sal_Int64);
    void UpdateRole() {} // Role recomputation is outside the focus-cache contract.
};

class AccObjectWinManager {
public:
    XAccessible* oldFocus=nullptr;
    std::map<XAccessible*,AccObject*> objects;
    std::map<long,IMAccessible*> ids;
    AccObject* GetAccObjByXAcc(XAccessible* value) {
        const auto found=objects.find(value);
        return found==objects.end()?nullptr:found->second;
    }
    IMAccessible* GetIAccessibleFromResID(long value) {
        const auto found=ids.find(value);
        return found==ids.end()?nullptr:found->second;
    }
    void UpdateAccFocus(XAccessible*);
};
AccObjectWinManager* CMAccessible::g_pAccObjectManager=nullptr;

#ifdef WINACC_CANDIDATE
#include "candidate_methods.inc"
#else
#include "extracted_methods.inc"
#endif

struct Node {
    XAccessible x;
    CMAccessible acc;
    AccObject object;
    Node(AccObjectWinManager& manager, std::uint32_t id, Node* parent=nullptr)
        :x{id},object(&acc,parent?&parent->object:nullptr) {
        acc.m_dChildID=id;
        acc.m_pIParent=parent?&parent->acc:nullptr;
        const bool a=manager.objects.emplace(&x,&object).second;
        const bool b=manager.ids.emplace(id,&acc).second;
        assert(a && b);
    }
};
struct Fixture {
    AccObjectWinManager manager;
    Node root{manager,1};
    Node a{manager,2,&root};
    Node b{manager,3,&root};
    Node other_root{manager,11};
    Node other{manager,12,&other_root};
    Fixture() { CMAccessible::g_pAccObjectManager=&manager; }
    ~Fixture() { CMAccessible::g_pAccObjectManager=nullptr; }
};
struct Observation {
    bool match=false;
    bool getter_observed=false;
    HRESULT result=0;
    std::uint16_t variant_type=0;
    long observed_id=0;
};
Observation observe(CMAccessible& root,CMAccessible* expected) {
    VARIANT value;
    Observation result;
    result.getter_observed=true;
    result.result=root.get_accFocus(&value);
    result.variant_type=value.vt;
    if(value.vt==VT_DISPATCH && value.pdispVal) {
        result.observed_id=value.pdispVal->m_dChildID;
        result.match=result.result==S_OK && value.pdispVal==expected;
        value.pdispVal->Release();
    } else result.match=result.result==S_OK && value.vt==VT_EMPTY && expected==nullptr;
    return result;
}

int main() {
    unsigned passed=0,failed=0;
    auto record=[&](std::string_view name, bool success, Observation observed={}) {
        passed+=success;failed+=!success;
        std::cout<<"{\"test\":\""<<name<<"\",\"passed\":"<<unsigned(success)
                 <<",\"getterObserved\":"<<unsigned(observed.getter_observed)
                 <<",\"hresult\":"<<observed.result<<",\"variantType\":"<<observed.variant_type
                 <<",\"observedId\":"<<observed.observed_id<<"}\n";
    };
    {
        Fixture f;const auto observed=observe(f.root.acc,nullptr);
        record("initial_root_has_no_focus",observed.match,observed);
    }
    {
        Fixture f;f.manager.UpdateAccFocus(&f.a.x);const auto observed=observe(f.root.acc,&f.a.acc);
        record("first_focus_returns_A",observed.match,observed);
    }
    {
        Fixture f;f.manager.UpdateAccFocus(&f.a.x);f.manager.UpdateAccFocus(&f.b.x);
        const auto observed=observe(f.root.acc,&f.b.acc);
        record("siblings_A_to_B_returns_B",observed.match,observed);
    }
    {
        Fixture f;f.manager.UpdateAccFocus(&f.a.x);f.manager.UpdateAccFocus(&f.a.x);
        const auto observed=observe(f.root.acc,&f.a.acc);
        record("same_object_keeps_A",observed.match && (f.a.acc.m_dState&STATE_SYSTEM_FOCUSED),observed);
    }
    {
        Fixture f;f.manager.UpdateAccFocus(&f.a.x);f.manager.UpdateAccFocus(&f.other.x);
        const auto before=observe(f.root.acc,nullptr),after=observe(f.other_root.acc,&f.other.acc);
        record("different_root_clears_old_and_sets_new",before.match && after.match,after);
    }
    {
        Fixture f;f.manager.UpdateAccFocus(&f.a.x);f.manager.UpdateAccFocus(nullptr);
        const auto observed=observe(f.root.acc,&f.a.acc);
        record("null_new_keeps_original_focus",observed.match && f.manager.oldFocus==&f.a.x,observed);
    }
    {
        Fixture f;XAccessible missing{99};f.manager.UpdateAccFocus(&f.a.x);f.manager.UpdateAccFocus(&missing);
        const auto observed=observe(f.root.acc,&f.a.acc);
        record("unknown_new_keeps_original_focus",observed.match && f.manager.oldFocus==&f.a.x,observed);
    }
    {
        Fixture f;Node left{f.manager,4,&f.root},right{f.manager,5,&f.root};
        Node a{f.manager,6,&left},b{f.manager,7,&right};
        f.manager.UpdateAccFocus(&a.x);f.manager.UpdateAccFocus(&b.x);
        const auto observed=observe(f.root.acc,&b.acc);
        record("deep_common_root_returns_new_leaf",observed.match,observed);
    }
    {
        Fixture f;f.manager.UpdateAccFocus(&f.a.x);f.manager.UpdateAccFocus(&f.b.x);
        const bool a=(f.a.acc.m_dState&STATE_SYSTEM_FOCUSED)!=0;
        const bool b=(f.b.acc.m_dState&STATE_SYSTEM_FOCUSED)!=0;
        record("state_bits_clear_old_and_set_new",!a && b);
    }
    {
        Fixture f;Observation observed;observed.getter_observed=true;
        observed.result=f.root.acc.get_accFocus(nullptr);
        record("null_variant_is_invalid_argument",observed.result==E_INVALIDARG,observed);
    }
    std::cout<<"{\"summary\":1,\"tests\":"<<passed+failed<<",\"passed\":"<<passed
             <<",\"failed\":"<<failed<<",\"hostLongBytes\":"<<sizeof(long)
             <<",\"actualWindows\":0,\"nativeAbiVerified\":0}\n";
    return failed?1:0;
}
