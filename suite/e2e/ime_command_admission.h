#pragma once
#include <cstdint>

namespace opengeul_ime {
struct CommandBudget { uint64_t counter=0, frequency=0; };
struct CommandAdmission { uint32_t active=0, attemptedMask=0; };
struct CommandRejection { uint32_t count=0, sequence=0, during=0, reason=0; };
inline bool InstallCommandBudget(CommandBudget (&slots)[4],uint32_t sequence,const CommandBudget& requested) {
    if (sequence<1 || sequence>4 || !requested.counter || !requested.frequency) return false;
    auto& slot=slots[sequence-1];
    if (slot.counter || slot.frequency) return false;
    slot=requested; return true;
}

// This is confined to the original hook thread (connect rejects all others).
// COM may pump a nested message on that same thread. Never let a restoration
// run inside an unfinished setter, or let a later command lend it more time.
class CommandLease {
    CommandAdmission& admission;
    bool entered=false;
public:
    const CommandBudget budget;
    const uint32_t sequence;
    CommandLease(CommandAdmission& admission,CommandRejection& rejection,
                 uint32_t sequence,const CommandBudget& published)
        : admission(admission),budget(published),sequence(sequence) {
        uint32_t reason=0;
        if (sequence<1 || sequence>4) reason=3;
        else {
            const auto bit=uint32_t(1)<<(sequence-1);
            if (admission.attemptedMask&bit) reason=2;
            else {
                admission.attemptedMask|=bit;
                if (admission.active) reason=1;
            }
        }
        if (reason) {
            if (rejection.count!=UINT32_MAX) ++rejection.count;
            rejection.sequence=sequence;rejection.during=admission.active;rejection.reason=reason;
        } else { admission.active=sequence;entered=true; }
    }
    CommandLease(const CommandLease&)=delete;
    CommandLease& operator=(const CommandLease&)=delete;
    bool Entered() const { return entered; }
    void Finish() { if (entered) { admission.active=0;entered=false; } }
    ~CommandLease() { Finish(); }
};
} // namespace opengeul_ime
