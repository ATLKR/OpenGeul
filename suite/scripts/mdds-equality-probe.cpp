// Investigation-only native ARM64 probe; no modified MDDS headers are supplied.
#include <mdds/flat_segment_tree.hpp>
#ifndef MDDS_PROBE_PARSE_ONLY
#include <stdexcept>
#include <utility>

struct throwing_value
{
    int value = 0;
    static inline bool throw_on_compare = false;
    bool operator==(const throwing_value& other) const noexcept(false)
    {
        if (throw_on_compare)
            throw std::runtime_error("expected comparison exception");
        return value == other.value;
    }
};

using scalar_tree = mdds::flat_segment_tree<int, int>;
using throwing_tree = mdds::flat_segment_tree<int, throwing_value>;
static_assert(noexcept(std::declval<const scalar_tree&>() == std::declval<const scalar_tree&>()));
static_assert(noexcept(std::declval<const scalar_tree&>() != std::declval<const scalar_tree&>()));
static_assert(!noexcept(std::declval<const throwing_tree&>() == std::declval<const throwing_tree&>()));
static_assert(!noexcept(std::declval<const throwing_tree&>() != std::declval<const throwing_tree&>()));

int main()
{
    scalar_tree a(0, 10, 0), b(0, 10, 0), different_key(0, 11, 0);
    if (!(a == b) || a != b || a == different_key)
        return 1;
    b.insert_front(2, 5, 1);
    if (a == b || !(a != b))
        return 2;
    scalar_tree copy(b);
    b.build_tree();
    if (!(b == copy) || b != copy)
        return 3;
    throwing_tree t1(0, 10, throwing_value{}), t2(0, 10, throwing_value{});
    if (!(t1 == t2))
        return 4;
    throwing_value::throw_on_compare = true;
    bool caught_eq = false, caught_ne = false;
    try { (void)(t1 == t2); }
    catch (const std::runtime_error&) { caught_eq = true; }
    try { (void)(t1 != t2); }
    catch (const std::runtime_error&) { caught_ne = true; }
    return caught_eq && caught_ne ? 0 : 5;
}
#else
int main() { return 0; }
#endif
