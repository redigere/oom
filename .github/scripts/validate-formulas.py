#!/usr/bin/env python3
import math
import sys

ZRAM_MIN = 2048
ZRAM_MAX = 16384

CORE_MIN = 1
CORE_RESERVE_DIVISOR = 8

WMSF_REF_VALUE = 500
WMSF_REF_RAM_MB = 8192
WMSF_MIN = 10
WMSF_MAX = 1000

EARLYOOM_TARGET_FREE_MB = 40000
EARLYOOM_PCT_MIN = 3
EARLYOOM_PCT_MAX = 10

NODE_HEAP_FRACTION = 0.5
NODE_HEAP_MIN_MB = 512

RAM_GUARD_MIN = 1


def target_zram_mb(ram_mb: int) -> int:
    return max(ZRAM_MIN, min(ram_mb, ZRAM_MAX))


def safe_core_limit(vcpus: int) -> int:
    return max(CORE_MIN, vcpus - math.ceil(vcpus / CORE_RESERVE_DIVISOR))


def watermark_scale_factor(ram_mb: int) -> int:
    return min(WMSF_MAX, max(WMSF_MIN, math.ceil(WMSF_REF_VALUE * WMSF_REF_RAM_MB / max(ram_mb, RAM_GUARD_MIN))))


def earlyoom_min_free_pct(ram_mb: int) -> int:
    return min(EARLYOOM_PCT_MAX, max(EARLYOOM_PCT_MIN, math.ceil(EARLYOOM_TARGET_FREE_MB / max(ram_mb, RAM_GUARD_MIN))))


def node_heap_mb(zram_mb: int) -> int:
    return max(NODE_HEAP_MIN_MB, int(zram_mb * NODE_HEAP_FRACTION))


violations = []


def check(cond: bool, msg: str):
    if not cond:
        violations.append(msg)


def check_nondecreasing(label: str, values: list):
    for i in range(1, len(values)):
        if values[i] < values[i - 1]:
            violations.append(f"NOT_NONDECREASING {label}: {values[i]} < {values[i - 1]} at index {i}")


def check_nonincreasing(label: str, values: list):
    for i in range(1, len(values)):
        if values[i] > values[i - 1]:
            violations.append(f"NOT_NONINCREASING {label}: {values[i]} > {values[i - 1]} at index {i}")


ram_fine_step = min(WMSF_REF_RAM_MB // 8, 1024)
ram_coarse_step = min(WMSF_REF_RAM_MB, 4096)
ram_range = sorted(set(
    list(range(0, WMSF_REF_RAM_MB, ram_fine_step))
    + list(range(WMSF_REF_RAM_MB, ZRAM_MAX * 2 + 1, ram_coarse_step))
    + [ZRAM_MIN, ZRAM_MAX, WMSF_REF_RAM_MB, EARLYOOM_TARGET_FREE_MB]
    + list(range(CORE_RESERVE_DIVISOR, min(ZRAM_MAX, EARLYOOM_TARGET_FREE_MB), CORE_RESERVE_DIVISOR))
))

zram_vals = [target_zram_mb(r) for r in ram_range]
wmsf_vals = [watermark_scale_factor(r) for r in ram_range]
eoom_vals = [earlyoom_min_free_pct(r) for r in ram_range]
node_vals = [node_heap_mb(z) for z in zram_vals]

for r, z in zip(ram_range, zram_vals):
    check(ZRAM_MIN <= z <= ZRAM_MAX, f"ZRAM_OOB ram={r}: got {z}")

for r, w in zip(ram_range, wmsf_vals):
    check(WMSF_MIN <= w <= WMSF_MAX, f"WMSF_OOB ram={r}: got {w}")

for r, e in zip(ram_range, eoom_vals):
    check(EARLYOOM_PCT_MIN <= e <= EARLYOOM_PCT_MAX, f"EARLYOOM_OOB ram={r}: got {e}")

for z, n in zip(zram_vals, node_vals):
    check(n >= NODE_HEAP_MIN_MB, f"NODE_FLOOR zram={z}: got {n}")

check_nondecreasing("zram", zram_vals)
check_nonincreasing("wmsf", wmsf_vals)
check_nonincreasing("earlyoom_pct", eoom_vals)
check_nondecreasing("node_heap", node_vals)

cpu_fine_step = max(1, 1024 // 256)
cpu_coarse_step = max(1, 1024 // 64)
cpu_range = list(range(1, cpu_fine_step * 64 + 1, cpu_fine_step)) + list(range(cpu_fine_step * 64 + cpu_coarse_step, 1025, cpu_coarse_step))
cpu_range = sorted(set(cpu_range))
core_vals = [safe_core_limit(c) for c in cpu_range]

for c, v in zip(cpu_range, core_vals):
    check(v >= CORE_MIN, f"CORE_FLOOR cpu={c}: got {v}")
    check(v <= c, f"CORE_EXCEED cpu={c}: got {v} > {c}")
    check(c - v >= math.ceil(c / CORE_RESERVE_DIVISOR) or c == CORE_MIN,
          f"CORE_NORESERVE cpu={c}: got {v}")

check_nondecreasing("safe_core", core_vals)

boundary_ram = sorted(set([
    0, RAM_GUARD_MIN, RAM_GUARD_MIN + 1,
    ZRAM_MIN - 1, ZRAM_MIN, ZRAM_MIN + 1,
    ZRAM_MAX - 1, ZRAM_MAX, ZRAM_MAX + 1,
    WMSF_REF_RAM_MB - 1, WMSF_REF_RAM_MB, WMSF_REF_RAM_MB + 1,
    EARLYOOM_TARGET_FREE_MB - 1, EARLYOOM_TARGET_FREE_MB, EARLYOOM_TARGET_FREE_MB + 1,
    WMSF_MAX, WMSF_MIN,
    CORE_RESERVE_DIVISOR, CORE_RESERVE_DIVISOR * CORE_RESERVE_DIVISOR,
]))

for r in boundary_ram:
    z = target_zram_mb(r)
    check(ZRAM_MIN <= z <= ZRAM_MAX, f"BOUNDARY_ZRAM_OOB ram={r}: got {z}")
    w = watermark_scale_factor(r)
    check(WMSF_MIN <= w <= WMSF_MAX, f"BOUNDARY_WMSF_OOB ram={r}: got {w}")
    e = earlyoom_min_free_pct(r)
    check(EARLYOOM_PCT_MIN <= e <= EARLYOOM_PCT_MAX, f"BOUNDARY_EARLYOOM_OOB ram={r}: got {e}")

boundary_cpu = sorted(set([CORE_MIN, CORE_MIN + 1, CORE_RESERVE_DIVISOR - 1, CORE_RESERVE_DIVISOR, CORE_RESERVE_DIVISOR + 1, 1024]))
for c in boundary_cpu:
    v = safe_core_limit(c)
    check(v >= CORE_MIN, f"BOUNDARY_CORE_FLOOR cpu={c}: got {v}")
    check(v <= c, f"BOUNDARY_CORE_EXCEED cpu={c}: got {v} > {c}")

if violations:
    for v in violations:
        sys.stderr.write(v + "\n")
    sys.exit(1)

sys.stdout.write(f"PASS {len(ram_range)}x3 {len(cpu_range)}\n")
