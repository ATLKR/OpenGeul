#include "windows_runtime.h"
#include <type_traits>

int main() {
    using opengeul::calc_dispatch::Scope;
    static_assert(sizeof(Scope) == 1);
    static_assert(std::is_nothrow_constructible_v<Scope, std::uint32_t>);
    Scope scope(1);
    scope.mark(3, 1);
}
