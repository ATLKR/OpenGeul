// Compile-only builtin trait control; see upstream example/multi_type_matrix.cpp.
#include <mdds/multi_type_matrix.hpp>
using matrix_type = mdds::multi_type_matrix<mdds::mtm::std_string_traits>;
bool observe_builtin_matrix_equality()
{
    matrix_type left(2, 2), right(2, 2);
    return (left == right) && !(left != right);
}
