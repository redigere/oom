# Configuration Rationale — Why Each Value

This document explains why every parameter in the OOM eradication playbook
is set to its specific value, what problem the value solves, and why the
project's choices differ from kernel defaults.

## vm.swappiness = 100

**Why not the default (60):** Default swappiness balances page cache eviction and swapping. On disk swap this is sensible — swap is slow, so you tolerate cache drops to avoid it. zRAM inverts the cost model: swapping to zRAM is fast (compression in RAM), while page cache drops force disk reads on rebuilds. Setting swappiness to 100 tells the kernel "swap anonymous pages aggressively before dropping page cache." This is correct when zRAM is large enough to hold the working set, because the most expensive operation in a build is re-reading source files and shared libraries from disk.

**Why not higher than 100:** The kernel clamps values above 100 to 100.

## vm.watermark_scale_factor: universal formula clamp(⌈500 × 8192 ÷ RAM⌉, 10, 1000)

**Why this formula instead of a fixed value:** watermark_scale_factor at value 500 (5% per zone) is correct for an 8 GB machine: each watermark zone is ~400 MB, giving kswapd enough runway to smooth allocation bursts. But 5% of 128 GB is 6.4 GB per zone — absurdly early reclaim that wastes memory. 5% of 2 GB is 100 MB per zone — reasonable for small machines. The absolute reclaim headroom per zone should be roughly constant across machines. The formula uses 8 GB as the reference point (where value 500 is known-good) and scales inversely with RAM: `500 × 8192 ÷ RAM_MB`. Results are clamped between 10 (default, 0.1% per zone) and 1000 (kernel max, 10% per zone).

**How it scales:**
- 2 GB → 1000 (10% per zone, ~200 MB/zone — aggressive early reclaim for tight memory)
- 4 GB → 1000 (10% per zone, ~400 MB/zone — clamped to max)
- 8 GB → 500 (5% per zone, ~400 MB/zone — reference point)
- 16 GB → 250 (2.5% per zone, ~400 MB/zone — smooth transition)
- 32 GB → 125 (1.25% per zone, ~400 MB/zone)
- 64 GB → 63 (0.63% per zone, ~400 MB/zone)
- 128 GB → 32 (0.32% per zone, ~400 MB/zone — close to default)

**Why not the default (10):** At 10, each zone on any machine is 0.1% of memory. On a 2 GB machine that is 2 MB per zone — the gap between min and max watermark is 6 MB. A single `rustc` invocation can allocate 200 MB in under a second, overshooting the entire watermark gap and stalling the process for direct reclaim. The formula ensures the absolute gap (in MB) is sufficient for bursty dev allocation patterns regardless of total RAM.

## vm.vfs_cache_pressure = 50

**Why not the default (100):** At 100, the kernel reclaims VFS caches (dentries, inodes) at the same rate as page cache. A C++ or Rust build opens the same headers hundreds of times. Each evicted dentry forces a directory lookup and inode load from disk on the next stat(). At 50, the reclaim rate is halved: VFS objects live longer across build invocations. The memory cost is small because dentries are compact (~200 bytes each); even a million dentries consumes ~200 MB, which zRAM easily absorbs.

**Why not 0:** At 0, the kernel never reclaims VFS caches, which can lead to unbounded memory growth on long-running machines. 50 is "prefer to keep them but still reclaim under pressure."

## vm.dirty_ratio, vm.dirty_background_ratio = 5, 2

**Why not the default (20/10):** When dirty page count reaches dirty_ratio, every write() syscall blocks until pages are flushed to storage. On a 32 GB machine with default 20%, 6.4 GB of dirty pages accumulate before writes block — causing a multi-second system-wide freeze as the storage stack drains the entire backlog. Lowering to 5%/2% caps the writeback burst at 1.6 GB on the same machine. The cost is more frequent background flushes, which are invisible on SSD.

**Why these values:** 5% is high enough that bursty compilers never block. 2% ensures the background flusher starts early. These are fixed percentages — no hardware scaling needed because the absolute cap scales linearly with RAM.

## vm.min_free_kbytes = max(64 MB, 0.1% of RAM)

**Why not the default (auto-calculated):** The kernel computes min_free_kbytes as a fraction of lowmem (~0.04%). This is tuned for servers that prefer to use all memory before reclaiming. On a desktop with bursty allocators, this leaves no runway for urgent allocations. The project's formula guarantees at least 64 MB floor, then 0.1% of total RAM above that. On a 2 GB machine: 64 MB (floor). On a 128 GB machine: ~131 MB. This scales with RAM but never drops below a safe minimum.

## vm.admin_reserve_kbytes = max(4 MB, 0.025% of RAM)
## vm.user_reserve_kbytes = max(16 MB, 0.05% of RAM)

**Why not the default (auto-calculated):** The kernel reserves 3% of lowmem for admin and 1.67% for user by default. On a 128 GB machine this wastes ~4 GB for admin. On a 2 GB machine it reserves ~60 MB — insufficient under pressure. The project's formulas scale reserves proportionally to RAM with floors that guarantee recovery headroom on every machine.

## vm.compaction_proactiveness = clamp(20 + 60 × 4096 ÷ RAM, 20, 80)

**Why not the default (20):** Memory compaction defragments physical memory to satisfy huge page allocations. At default 20, the kernel compacts lazily — reactive rather than proactive. When a large allocation arrives and no contiguous pages exist, the allocating thread stalls for compaction. This is the primary cause of "jank" on desktops under memory pressure.

**Why inverse-RAM formula:** Smaller machines fragment faster because their smaller page pools are exhausted and recycled more frequently. The formula sets compaction aggressiveness inversely to RAM: on 2 GB: 80 (aggressive), on 8 GB: 50 (moderate), on 32 GB: 28 (gentle), on 128 GB: 22 (minimal). This ensures small machines compact proactively to avoid stalls, while large machines save CPU time because they have enough headroom to absorb fragmentation naturally.

## vm.page_lock_unfairness = 1

**Why not the default (5):** When the kernel reclaims pages under memory pressure, it skips recently-locked pages up to `page_lock_unfairness` times before picking a different victim. Default 5 means a heavily contended page can be skipped 5 times, pushing reclaim work onto other tasks and causing uneven latency. The project sets 1 — the minimum — making reclaim fairer and distributing pressure evenly across all processes. This value does not scale with hardware: fairness is equally important on all machine sizes.

## vm.zone_reclaim_mode = 0

**Why not the default (0):** Already the default, but set explicitly because some NUMA tuning guides recommend 1 (prefer local zone). On a desktop, zone reclaim causes unnecessary page migration and latency spikes when the kernel tries to keep allocations local at all costs. 0 allows the kernel to allocate from any zone. This is a policy choice, not a hardware-dependent value.

## vm.reap_mem_on_sigkill = 1

**Why not the default (0):** When the kernel delivers SIGKILL, it normally does not reclaim the victim's memory immediately — the memory remains allocated until the next scan. Under extreme memory pressure, this means a killed process's memory stays in use for hundreds of milliseconds, during which the system remains frozen. The project sets 1, telling the kernel to reclaim the victim's memory synchronously on SIGKILL. This is a fixed policy: immediate reclaim is always beneficial regardless of machine size.

## vm.oom_dump_tasks = 0

**Why not the default (1):** When the kernel OOM killer activates, it prints /proc/pid/status for every process in the system to the kernel log. On a machine with thousands of processes, this dump takes seconds while the system is already frozen. The project suppresses the dump entirely, allowing the OOM killer to select a victim and reclaim memory immediately. This is always correct — OOM diagnostics are useless if the system is frozen.

## THP Defrag = madvise

**Why not the default (always):** The kernel's transparent hugepage defragmenter runs compaction when 2 MB hugepage allocations fail. In "always" mode, compaction runs for any hugepage allocation, including those that are not performance-critical. Compaction is a blocking operation: it scans and migrates pages in a loop, and the allocating thread stalls until a contiguous region is found. Setting to "madvise" tells the compaction thread to run only for pages explicitly requested via MADV_HUGEPAGE. This eliminates unpredictable latency spikes from background compaction — the most common source of "jank" on Linux desktops under memory pressure.

**Why not never:** Some workloads (database, JVM, V8) benefit from hugepages for TLB performance. "madvise" allows them to opt in via mmap flags while keeping all other allocations safe from compaction stalls.

## MGLRU = 7 (bitmask: 1|2|4)

**Why enable MGLRU (bit 1):** The default single-LRU algorithm uses one list for all page generations, making it prone to scanning hot pages when cold pages are scattered. MGLRU maintains multiple generations (young to old), aging pages without scanning the entire list. This is particularly beneficial for dev workloads: editors, browsers, language servers have long-lived anonymous pages that should not be scanned repeatedly; build processes have short-lived pages that should be reclaimed quickly.

**Why page table walks (bit 2):** Without bit 2, MGLRU relies on idle page tracking (from /sys/kernel/mm/page_idle) for aging. Page table walks are cheaper and do not require the idle page tracking infrastructure. They also work on any Linux kernel without additional configuration.

**Why proactive reclaim (bit 4):** Proactive reclaim scans PTEs in the background and evicts cold pages before memory pressure hits. On a dev machine, this is valuable because it converts direct reclaim stalls (which pause the allocating thread) into background kswapd work. The developer experiences fewer "jank" moments during build starts.

**Why not a lower value (e.g., 3 = bits 1|2 only):** Without proactive reclaim, MGLRU only reacts to pressure after it arrives. Proactive reclaim predicts pressure and acts preemptively, which is the primary benefit for workstation responsiveness.

## PSI = 1 (kernel cmdline)

**Why enable PSI:** Without PSI, earlyoom monitors free memory and swap via /proc/meminfo. This is misleading under zRAM because Committed_AS counts all committed pages (including compressed ones), making it appear that free memory is lower than it is. PSI measures actual stall time: the fraction of time tasks are waiting on memory. earlyoom can use `/proc/pressure/memory` to trigger on real resource contention rather than synthetic memory pressure.

**Why not PSI = 1 as a sysctl:** PSI is a compile-time and boot-time option. The kernel parameter `psi=1` enables the feature. There is no runtime toggle; it must be set on the kernel command line.

## zRAM compression = zstd

**Why zstd instead of lz4 or lzo:** lz4 and lzo are faster at compression/decompression but achieve worse ratios. On a memory-constrained workstation, ratio matters more than throughput because zRAM is not on the hot path (anonymous pages are swapped out once and may never be swapped back in if not accessed). zstd achieves ~2-3x compression on typical anonymous page data (heap, stack, mmap'd files) versus ~1.5-2x for lzo. The extra CPU cost is invisible on modern hardware because zRAM compression runs in the background via kswapd.

**Why zstd instead of zlib:** zlib achieves slightly better ratios than zstd but is significantly slower at both compression and decompression. Decompression speed matters when a swapped-out page is faulted back in (e.g., when resuming a swapped-out build process). zstd decompression is ~3x faster than zlib.

## zRAM priority = 100

**Why priority 100:** The kernel selects the swap device with the highest priority first. Setting zRAM priority to 100 (higher than default 0 and higher than most disk swap configurations) ensures the kernel swaps to zRAM before touching any remaining disk swap. Without this, the kernel might swap to disk in parallel with zRAM, causing latency spikes when it picks the slow device.

## zRAM size: universal formula max(2048, min(RAM_MB, 16384))

**Why this formula instead of a threshold:** A hard threshold at 8 GB creates a discontinuity: an 8 GB machine gets 8 GB zRAM, an 8.1 GB machine gets 16 GB — a 2× jump for 100 MB of extra RAM. The universal formula `max(2048, min(RAM_MB, 16384))` produces a smooth linear function between floor (2 GB) and cap (16 GB). There is no threshold, no discontinuity.

**How it scales:**
- 1 GB → 2 GB (floor — smallest machine still gets useful compressed swap)
- 2 GB → 2 GB
- 4 GB → 4 GB
- 8 GB → 8 GB
- 12 GB → 12 GB (instead of jumping to 16 GB)
- 16 GB → 16 GB (cap begins)
- 32 GB → 16 GB (capped)
- 128 GB → 16 GB (capped)

**Why full zRAM up to 16 GB of RAM:** zstd compression achieves ~2-3× on anonymous page data. 16 GB zRAM holds 32-48 GB of effective swap — sufficient for any dev workload including multiple simultaneous builds. Below 16 GB RAM, zRAM equals physical RAM, giving the VM 2-3× effective memory via compression.

**Why 2 GB floor:** A 1-2 GB machine (netbook, thin client, VM) cannot afford 1:1 zRAM because zsmalloc pool overhead + compressed pages + running system would consume >90% of RAM. 2 GB zRAM provides ~4-6 GB effective swap while leaving enough physical RAM for the OS and a lightweight dev environment.

**Why 16 GB cap:** Beyond 16 GB of zRAM, the marginal benefit drops: the working set of anonymous pages on a dev machine rarely exceeds 16 GB (uncompressed). Additional zRAM would waste CPU compressing pages that are never faulted in and compete with page cache for physical RAM.

## earlyoom -m: universal formula clamp(⌈40000 ÷ RAM_MB⌉, 3, 10)

**Why this formula instead of a fixed percentage:** A fixed `-m 5` (kill when free < 5%) means different absolute thresholds on different machines: 100 MB on a 2 GB machine (too tight) versus 6.4 GB on a 128 GB machine (too generous). The formula targets a constant absolute free memory of ~400 MB as the OOM trigger point, then converts back to a percentage of total RAM. `40000 ÷ RAM_MB` gives: on 8 GB: 40000/8192 ≈ 5%; on 2 GB: 40000/2048 ≈ 20% (clamped to 10%); on 128 GB: 40000/131072 ≈ 0.3% (clamped to 3% floor).

**How it scales:**
- 2 GB → 10% (~200 MB free trigger — aggressive but safe with zRAM)
- 4 GB → 10% (~400 MB free trigger — clamped to max)
- 8 GB → 5% (~400 MB free trigger — reference point)
- 16 GB → 3% (~480 MB free trigger — floor)
- 32 GB → 3% (~960 MB free trigger — floor)
- 128 GB → 3% (~3.8 GB free trigger — floor)

**Why -s 10 (kill at 10% free swap):** Universal constant — swap is a limited pool proportional to zRAM size (which already scales with RAM). 10% free swap indicates the zRAM device is 90% saturated regardless of machine size. On a 16 GB zRAM: 1.6 GB remaining. On a 2 GB zRAM: 200 MB remaining. Both are reasonable OOM trigger points for a thrashing system.

**Why not a fixed -m:** The absolute amount of "emergency headroom" should be similar across machines — a developer on a 128 GB workstation should not get 100× more warning time than one on a 2 GB laptop. The percentage adjusts so that the absolute free memory at trigger point hovers around 400-1000 MB, which is enough to flush caches and SIGTERM a build process without OOM-killing the desktop.

## earlyoom avoid/prefer regexes

**Why avoid init, systemd:** These are PID 1 and service manager; killing them crashes the system.

**Why avoid Xorg, Xwayland, wayland, gnome-shell, kwin, mutter, hyprland, sway, xfwm4:** These are the display server, window manager, and compositor. Killing them terminates the graphical session, losing all unsaved work.

**Why avoid codium, code, idea, studio, eclipse, nvim, emacs:** These are editors and IDEs with unsaved state. Losing editor state is the most disruptive event for a developer.

**Why avoid bash, zsh, firefox, chrome, chromium, brave:** Shells and browsers have significant user state (tabs, scrollback, sessions). Killing them is disruptive but less critical than editors.

**Why prefer cc1plus, rustc, cargo, node, java, webpack, esbuild, npm, make, ninja, cmake, docker, containerd:** These are compilers, build tools, bundlers, and container runtimes — the primary memory consumers on a dev machine. They are stateless from the user's perspective: killed process exits, next build restarts it. Preferring them ensures the kernel OOM killer (called when earlyoom SIGTERM fails) does not pick a desktop process instead.

**Why the ^|/ and $ anchors:** The regex `(^|/)cc1plus$` matches `/usr/lib/gcc/.../cc1plus` but not a process named `cc1plus-background` or `my-cc1plus-tool`. The anchors prevent partial matches from accidentally protecting or sacrificing unintended processes.

## User Slice Memory Limit: MemoryMax=90%

**Why not unlimited (systemd default):** Without a cgroupv2 memory limit on user.slice, a single user session can consume all physical RAM plus all zRAM swap. When every page is exhausted, the kernel has no headroom to run the OOM killer, flush dirty pages, or deliver signals — the system enters an unbounded livelock where all processes are in D state (uninterruptible sleep waiting for memory). This is the "desktop freeze" that persists until the hardware watchdog resets the machine.

**Why 90% instead of 100%:** Reserving 10% of physical RAM guarantees that the kernel, systemd, and earlyoom always have allocatable memory even when the user session exceeds its limit. The 10% reserved pool is used for: OOM killer page reclaim, SIGTERM/SIGKILL signal delivery, page table allocation for the killing path, dirty page writeback threads, and systemd emergency services. On a 32 GB machine, 3.2 GB of reserved memory is more than enough for recovery; on a 2 GB machine, 200 MB still suffices.

**Why not lower than 90%:** If the limit is too strict (e.g., 50%), the user session hits the cgroup OOM killer during normal workloads, killing the IDE or browser. 90% is the safety net for runaway processes, not an active limit during normal operation.

**Why TasksMax=infinity:** The default TasksMax for user.slice is 33% of pids_max (roughly 10,000 on most systems). A power user running many apps (browser with hundreds of tabs, IDE, language servers, containers) can exhaust this limit, preventing fork() and exec() system calls — causing apparent freezes because no new process can start. Removing the limit ensures the user can always spawn new processes.

## CARGO_BUILD_JOBS, MAKEFLAGS, NINJAJOBS = safe_core_limit

### Formula: max(1, vCPU − ceil(vCPU ÷ 8))

**Why this formula instead of a threshold:** A threshold at 4 vCPUs (reserve 1 core ≤4, reserve 2 cores >4) creates a discontinuity: a 4-core machine gets 3 build cores, a 5-core machine also gets 3 (5-2=3). The universal formula `max(1, vCPU − ceil(vCPU/8))` smoothly reserves 1 core for every 8 available, with a floor of 1. On a 4-core machine: ceil(4/8) = 1 reserved. On a 16-core machine: ceil(16/8) = 2 reserved. On a 128-core machine: ceil(128/8) = 16 reserved. The proportion of reserved cores decreases as total cores increase (12.5% reserved on large machines, 25-50% on small ones), which is correct because the desktop's CPU needs grow sub-linearly with total cores.

**Why limit parallelism:** Build tools default to all available CPUs. On a 16-core machine, 16 parallel compile jobs may each use 1-2 GB of memory at peak, demanding 16-32 GB of anonymous pages. This competes with zRAM capacity and slows the system. The formula reserves enough cores for the desktop (window manager, input, browser, editor) to stay responsive while dedicating the rest to build throughput.

## NODE_OPTIONS --max-old-space-size = max(512, target_zram_mb × 0.5)

**Why limit Node.js heap:** Node.js V8's garbage collector performs full GC (stop-the-world) when the old space grows large. A full GC on an 8 GB heap can take seconds, freezing the process. Limiting heap prevents this. 50% of zRAM is a safe heuristic: it prevents Node from consuming the entire compressed swap pool, leaving room for other processes. If zRAM is 16 GB, Node gets 8 GB max heap, which is sufficient for webpack, esbuild, or any Node-based build tool.

**Why the 512 MB floor:** On machines with 2 GB RAM (zRAM = 2 GB), 50% zRAM gives Node only 1 GB max heap. On a machine where the same Node process may build a large application, 1 GB may trigger OOM within the Node process itself. The floor at 512 MB ensures Node always has at least 512 MB of heap regardless of zRAM size, preventing premature GC pressure on the smallest supported machines.
