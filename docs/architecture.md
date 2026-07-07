# Architecture — Why

## Why Five Roles In This Order

Each role depends on data or state established by the preceding role. The sequence is not arbitrary.

### 1. system_discovery first

The three consuming roles (zram_swap, dev_throttling, kernel_tuning) all need platform-aware parameters. zram_swap needs OS family to select the correct package name and config template. dev_throttling needs RAM and CPU counts. kernel_tuning needs to know whether GRUB is present. Gathering these facts up front avoids duplicating discovery logic across roles and guarantees a single source of truth for derived values.

### 2. kernel_tuning second

earlyoom (configured later by oom_handler) relies on PSI being enabled at boot. If PSI is not in the kernel command line, earlyoom falls back to less accurate /proc/meminfo heuristics. Enabling PSI via GRUB (and MGLRU via sysfs) before the OOM handler runs ensures the kernel interface earlyoom needs is active. sysctl parameters (swappiness, watermark_scale_factor, vfs_cache_pressure) are independent of other roles but logically belong with kernel tuning.

### 3. zram_swap third

zRAM must be configured before earlyoom runs, because earlyoom's behavior depends on swap availability (the `-s` flag monitors free swap percent). If disk swap is disabled and zRAM is not yet active, earlyoom sees 0 swap and may trigger prematurely. Disk swap must also be disabled before zRAM is brought up because the kernel prefers lower-priority swap devices; an active disk swap at higher priority would be used before zRAM, defeating the purpose.

### 4. oom_handler fourth

earlyoom must start after zRAM is active and PSI is enabled, for the reasons above. The role also masks systemd-oomd, which would compete with earlyoom for OOM policy control. Both daemons cannot coexist coherently: systemd-oomd uses cgroup-based pressure thresholds, earlyoom uses system-wide free memory and PSI. They would act on different signals and potentially fight each other.

### 5. dev_throttling last

Environment limits in /etc/profile.d/dev-limits.sh are a soft governance layer applied at shell login. They do not depend on kernel state, swap devices, or OOM daemon configuration. Placing this role last ensures every other subsystem is fully configured before resource limits are defined, so the limits reflect the actual memory (zRAM) and CPU (reserved cores) landscape.

## Why Flat Dependencies (No meta/main.yml)

Ansible role dependencies via meta/main.yml are resolved at parse time, before any task runs. This means they cannot reference `set_fact` variables from other roles. Since the coupling between these roles is purely data-driven (facts computed in system_discovery are consumed by later roles), the dependency is necessarily ordering-based, not metadata-based. Flat dependencies also mean each role can be run independently with explicit `--extra-vars` for testing, without Ansible trying to resolve a dependency graph.

## Why Data Coupling Instead of Global Vars

The three derived values (target_zram_mb, safe_core_limit, os_family) could be hardcoded as playbook-level variables. They are computed at runtime instead because the values depend on the target machine's RAM and CPU count, which vary per host and are read by `gather_facts: true`. Hardcoding would mean different configs for different workstations; runtime computation makes the playbook portable across machines with no edits.

## Why Universal Formulas Instead of Thresholds

All five computed parameters (zRAM, safe_cores, watermark_scale_factor, earlyoom_pct, node_heap) use **continuous functions** of RAM or vCPUs instead of discrete thresholds. The motivation: a threshold at 8 GB or 4 vCPUs creates a discontinuity where two nearly-identical machines (7.9 GB vs 8.1 GB RAM) get radically different configurations. Continuous functions minimize `|X-Y|` — the absolute difference between ideal config and applied config — across the entire hardware spectrum from 2 GB laptops to 128 GB workstations.

## Why target_zram_mb: max(2048, min(RAM_MB, 16384))

A pure continuous function with floor at 2 GB (prevents zRAM from starving physical RAM on tiny machines) and cap at 16 GB (prevents wasting CPU on rarely-accessed compressed pages on large machines). Between floor and cap, zRAM equals physical RAM — the simplest possible formula with no threshold. Compared to the old threshold formula: a 12 GB machine gets 12 GB zRAM instead of 16 GB (saving 4 GB of compression overhead), a 2 GB machine gets 2 GB instead of 2 GB (same), a 24 GB machine gets 16 GB instead of 16 GB (same).

## Why safe_core_limit: max(1, vCPU − ceil(vCPU ÷ 8))

Reserves 1 core for every 8 available (∼12.5%) with floor at 1. This is a continuous function — no threshold at 4 vCPUs. A 2-core machine reserves 1 core (same as old formula), a 4-core machine reserves 1 (was: 1), an 8-core machine reserves 1 (was: 2), a 16-core machine reserves 2 (was: 2), a 128-core machine reserves 16 (was: 2). The key difference: on large machines (>16 cores), the function reserves proportionally more cores for the desktop, which is correct because more cores mean more competing processes (heavier browser, more IDE plugins, background services).

## Why watermark_scale_factor: clamp(⌈500 × 8192 ÷ RAM_MB⌉, 10, 1000)

Inversely proportional to RAM, using 8 GB as reference point (value 500 is known-good). The goal: keep absolute reclaim zone size approximately constant (~400 MB/zone) regardless of total RAM. Without this scaling, a 128 GB machine would have 6.4 GB/zone — reclaim would start when free memory drops below 19 GB, which is absurdly early.

## Why earlyoom_min_free_pct: clamp(⌈40000 ÷ RAM_MB⌉, 3, 10)

Inversely proportional to RAM, targeting ~400 MB absolute free memory as OOM trigger. A fixed `-m 5` on a 128 GB machine would trigger at 6.4 GB free (too early), on a 2 GB machine at 100 MB free (too late). The formula normalizes the trigger to an absolute value, then expresses it as a percentage of total RAM.
