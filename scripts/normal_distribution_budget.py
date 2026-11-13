"""Finite normal HWP distribution budgets, separate from Store product limits."""

# One architecture includes its required MSIX, portable ZIP and source/WACK metadata.
ARCH_LIMIT = 128 * 1024 * 1024
# Both architectures plus the fixed global Source descriptor/checksum files.
PAIR_LIMIT = 256 * 1024 * 1024
