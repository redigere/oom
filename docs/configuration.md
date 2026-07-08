# Configuration Rationale — Each Value

This document describes each parameter in the OOM eradication playbook:
what problem it solves and how it differs from kernel defaults.

## vm.swappiness = 10

Default swappiness (60) treats page cache eviction and anonymous page swapping
as roughly equal cost. On a desktop with zRAM, this is wrong: anonymous page
swapping carries a real CPU cost (zstd compression on swapout, decompression
on swapin), while page cache eviction is free (just drop the page, no I/O
unless dirty). Page cache can be transparently re-read from disk on access;
zRAM decompression blocks the faulting thread with CPU-bound work. Low
swappiness tells the kernel to strongly prefer dropping page cache over
swapping anonymous pages, keeping application memory hot in RAM.

**10 instead of 1:** A value of 1 means "never swap unless absolute last
resort," which under extreme memory pressure causes the kernel to stall
processes in direct reclaim while scanning page cache. 10 provides a slight
preference for cache eviction while still allowing kswapd to swap proactively
before pressure becomes critical. zRAM remains as a safety net for genuine
memory oversubscription, not as a primary reclaim target.

**Not 100 (previous version):** swappiness=100 inverts the cost model, telling
the kernel to swap anonymous pages before dropping page cache. This is correct
when the goal is build cache performance (re-reading files from disk is slower
than decompressing from zRAM) but incorrect for desktop fluidity. The CPU cost
of zstd compression/decompression on every swapped page causes visible
stuttering when switching between applications. Anonymous pages contain editor
buffers, browser tabs, terminal scrollback, and language server state — these
must stay in physical RAM for instant response.

## vm.watermark_scale_factor: clamp(ceil(500 * 8192 / RAM), 10, 1000)

watermark_scale_factor at value 500 (5% per zone) is correct for an 8 GB
machine: each watermark zone is ~400 MB, giving kswapd enough runway to smooth
allocation bursts. But 5% of 128 GB is 6.4 GB per zone — absurdly early reclaim
that wastes memory. 5% of 2 GB is 100 MB per zone — reasonable. The absolute
reclaim headroom per zone should be roughly constant across machines. The
formula uses 8 GB as the reference point (where value 500 is known-good) and
scales inversely with RAM: `500 * 8192 / RAM_MB`. Results are clamped between
10 (default, 0.1% per zone) and 1000 (kernel max, 10% per zone).

**Scaling:**
- 2 GB: 1000 (10% per zone, ~200 MB/zone — aggressive early reclaim)
- 8 GB: 500 (5% per zone, ~400 MB/zone — reference point)
- 16 GB: 250 (2.5% per zone, ~400 MB/zone)
- 32 GB: 125 (1.25% per zone, ~400 MB/zone)
- 128 GB: 32 (0.32% per zone, ~400 MB/zone — close to default)

**Not the default (10):** At 10, each zone is 0.1% of memory. On a 2 GB
machine that is 2 MB per zone — the gap between min and max watermark is 6 MB.
A single `rustc` invocation allocates 200 MB in under a second, overshooting
the entire watermark gap and stalling for direct reclaim.

## vm.vfs_cache_pressure = 50

At default 100, the kernel reclaims VFS caches (dentries, inodes) at the same
rate as page cache. A C++ or Rust build opens the same headers hundreds of
times; each evicted dentry forces a directory lookup and inode load from disk
on the next stat(). At 50, the reclaim rate is halved: VFS objects live longer
across build invocations. The memory cost is small because dentries are compact
(~200 bytes each).

**Not 0:** At 0, the kernel never reclaims VFS caches, leading to unbounded
memory growth on long-running machines. 50 means "prefer to keep them but still
reclaim under pressure."

## vm.dirty_ratio, vm.dirty_background_ratio = 5, 2

At default 20/10, when dirty page count reaches dirty_ratio, every write()
syscall blocks until pages are flushed to storage. On a 32 GB machine with
20%, 6.4 GB of dirty pages accumulate before writes block — causing a
multi-second system-wide freeze as the storage drains the backlog. Lowering
to 5%/2% caps the writeback burst at 1.6 GB on the same machine. The cost is
more frequent background flushes, invisible on SSD. These are fixed percentages
because the absolute cap scales linearly with RAM.

## vm.min_free_kbytes = max(64 MB, 0.1% of RAM)

The kernel auto-calculates min_free_kbytes as a fraction of lowmem (~0.04%),
tuned for servers that prefer to use all memory before reclaiming. On a desktop
with bursty allocators, this leaves no runway for urgent allocations. The
formula guarantees at least 64 MB floor, then 0.1% of total RAM above that.
On a 2 GB machine: 64 MB (floor). On a 128 GB machine: ~131 MB.

## vm.admin_reserve_kbytes = max(4 MB, 0.025% of RAM)
## vm.user_reserve_kbytes = max(16 MB, 0.05% of RAM)

The kernel defaults reserve 3% of lowmem for admin and 1.67% for user. On a
128 GB machine this wastes ~4 GB for admin. On a 2 GB machine it reserves
~60 MB — insufficient under pressure. The formulas scale reserves
proportionally to RAM with floors that guarantee recovery headroom on every
machine.

## vm.compaction_proactiveness = clamp(20 + 60 * 4096 / RAM, 20, 80)

Memory compaction defragments physical memory to satisfy huge page allocations.
At default 20, the kernel compacts lazily — reactive rather than proactive.
When a large allocation arrives and no contiguous pages exist, the allocating
thread stalls for compaction. This is the primary cause of jank on desktops
under memory pressure.

Smaller machines fragment faster because their smaller page pools are exhausted
and recycled more frequently. The formula sets compaction aggressiveness
inversely to RAM: 2 GB: 80 (aggressive), 8 GB: 50 (moderate), 32 GB: 28
(gentle), 128 GB: 22 (minimal). Small machines compact proactively to avoid
stalls; large machines save CPU time because they have enough headroom.

## vm.page_lock_unfairness = 1

When the kernel reclaims pages under memory pressure, it skips recently-locked
pages up to `page_lock_unfairness` times before picking a different victim.
Default 5 means a heavily contended page can be skipped 5 times, pushing
reclaim work onto other tasks and causing uneven latency. Setting 1 — the
minimum — makes reclaim fairer and distributes pressure evenly. This value
does not scale with hardware: fairness is equally important on all machine
sizes.

## vm.zone_reclaim_mode = 0

Already the kernel default, but set explicitly because some NUMA tuning guides
recommend 1 (prefer local zone). On a desktop, zone reclaim causes unnecessary
page migration and latency spikes when the kernel tries to keep allocations
local at all costs. 0 allows the kernel to allocate from any zone.

## vm.reap_mem_on_sigkill = 1

When the kernel delivers SIGKILL, it normally does not reclaim the victim's
memory immediately — the memory remains allocated until the next scan. Under
extreme memory pressure, a killed process's memory stays in use for hundreds
of milliseconds, during which the system remains frozen. Setting 1 tells the
kernel to reclaim the victim's memory synchronously on SIGKILL.

## vm.oom_dump_tasks = 0

When the kernel OOM killer activates, it prints /proc/pid/status for every
process to the kernel log. On a machine with thousands of processes, this dump
takes seconds while the system is already frozen. Suppressing the dump allows
the OOM killer to select a victim and reclaim memory immediately.

## THP Defrag = madvise

The kernel's transparent hugepage defragmenter runs compaction when 2 MB
hugepage allocations fail. In "always" mode, compaction runs for any hugepage
allocation, including non-performance-critical ones. Compaction is a blocking
operation: it scans and migrates pages in a loop, and the allocating thread
stalls until a contiguous region is found. "madvise" tells compaction to run
only for pages explicitly requested via MADV_HUGEPAGE, eliminating
unpredictable latency spikes.

**Not never:** Some workloads (database, JVM, V8) benefit from hugepages for
TLB performance. "madvise" lets them opt in via mmap flags while keeping other
allocations safe from compaction stalls.

## MGLRU = 7 (bitmask: 1|2|4)

The default single-LRU algorithm uses one list for all page generations, making
it prone to scanning hot pages when cold pages are scattered. MGLRU maintains
multiple generations (young to old), aging pages without scanning the entire
list. This benefits dev workloads: editors, browsers, language servers have
long-lived anonymous pages that should not be scanned repeatedly; build
processes have short-lived pages that should be reclaimed quickly.

**Bit 2 (page table walks):** Without it, MGLRU relies on idle page tracking
from /sys/kernel/mm/page_idle for aging. Page table walks are cheaper and do
not require the idle page tracking infrastructure.

**Bit 4 (proactive reclaim):** Scans PTEs in the background and evicts cold
pages before memory pressure hits, converting direct reclaim stalls into
background kswapd work. Without it, MGLRU only reacts to pressure after it
arrives.

**Not a lower value (e.g., 3 = bits 1|2 only):** Without proactive reclaim,
MGLRU only reacts to pressure after it arrives. Proactive reclaim is the
primary benefit for workstation responsiveness.

## PSI = 1 (kernel cmdline)

Without PSI, earlyoom monitors free memory and swap via /proc/meminfo. This is
misleading under zRAM because Committed_AS counts all committed pages
(including compressed ones), making free memory appear lower than it is. PSI
measures actual stall time: the fraction of time tasks are waiting on memory.
earlyoom uses `/proc/pressure/memory` to trigger on real resource contention.

PSI is a compile-time and boot-time option. The kernel parameter `psi=1`
enables it. There is no runtime toggle; it must be set on the kernel command
line.

## zRAM compression = zstd

lz4 and lzo are faster at compression/decompression but achieve worse ratios.
On a memory-constrained workstation, ratio matters more than throughput because
zRAM is not on the hot path (anonymous pages are swapped out once and may never
be swapped back in). zstd achieves ~2-3x compression on typical anonymous page
data versus ~1.5-2x for lzo. The extra CPU cost is invisible on modern hardware
because zRAM compression runs in the background via kswapd.

**zstd vs zlib:** zlib achieves slightly better ratios than zstd but is
significantly slower at both compression and decompression. Decompression speed
matters when a swapped-out page is faulted back in (e.g., resuming a build
process). zstd decompression is ~3x faster than zlib.

## zRAM priority = 100

The kernel selects the swap device with the highest priority first. Setting
zRAM priority to 100 (higher than default 0 and most disk swap configurations)
ensures the kernel swaps to zRAM before touching disk swap.

## zRAM size: max(2048, min(RAM_MB, 16384))

A hard threshold at 8 GB creates a discontinuity: 8 GB machine gets 8 GB zRAM,
8.1 GB gets 16 GB — a 2x jump for 100 MB extra RAM. The universal formula
produces a smooth linear function between floor (2 GB) and cap (16 GB).

**Scaling:**
- 1 GB: 2 GB (floor)
- 4 GB: 4 GB
- 8 GB: 8 GB
- 12 GB: 12 GB (instead of jumping to 16 GB)
- 16 GB: 16 GB (cap begins)
- 128 GB: 16 GB (capped)

**2 GB floor:** A 1-2 GB machine cannot afford 1:1 zRAM because zsmalloc pool
overhead + compressed pages + running system would consume >90% of RAM. 2 GB
zRAM provides ~4-6 GB effective swap while leaving enough physical RAM for the
OS and a lightweight dev environment.

**16 GB cap:** The working set of anonymous pages on a dev machine rarely
exceeds 16 GB (uncompressed). Additional zRAM wastes CPU compressing pages
that are never faulted in and competes with page cache for physical RAM.

## earlyoom -m: clamp(ceil(40000 / RAM_MB), 3, 10)

A fixed `-m 5` (kill when free < 5%) means different absolute thresholds: 100 MB
on a 2 GB machine (too tight) versus 6.4 GB on a 128 GB machine (too generous).
The formula targets a constant absolute free memory of ~400 MB as the OOM
trigger point, then converts back to a percentage. `40000 / RAM_MB` gives:
on 8 GB: 40000/8192 ~ 5%; on 2 GB: 40000/2048 ~ 20% (clamped to 10%); on
128 GB: 40000/131072 ~ 0.3% (clamped to 3% floor).

**Scaling:**
- 2 GB: 10% (~200 MB free trigger)
- 4 GB: 10% (~400 MB free trigger)
- 8 GB: 5% (~400 MB free trigger)
- 16 GB: 3% (~480 MB free trigger)
- 128 GB: 3% (~3.8 GB free trigger)

**-s 10 (kill at 10% free swap):** Universal constant — swap is a limited pool
proportional to zRAM size. 10% free swap indicates the zRAM device is 90%
saturated regardless of machine size. On 16 GB zRAM: 1.6 GB remaining. On 2 GB
zRAM: 200 MB remaining.

## earlyoom avoid/prefer regexes

**avoid init, systemd:** PID 1 and service manager; killing them crashes the
system.

**avoid Xorg, Xwayland, wayland, gnome-shell, kwin, mutter, hyprland, sway, xfwm4:**
Display server, window manager, and compositor. Killing them terminates the
graphical session, losing all unsaved work.

**avoid codium, code, idea, studio, eclipse, nvim, emacs:** Editors and IDEs
with unsaved state. Losing editor state is the most disruptive event for a
developer.

**avoid bash, zsh, firefox, chrome, chromium, brave:** Shells and browsers with
significant user state (tabs, scrollback, sessions). Disruptive but less
critical than editors.

**prefer cc1plus, rustc, cargo, node, java, webpack, esbuild, npm, make, ninja,
cmake, docker, containerd:** Compilers, build tools, bundlers, and container
runtimes — the primary memory consumers on a dev machine. They are stateless:
killed process exits, next build restarts it. Preferring them ensures the
kernel OOM killer (invoked when earlyoom SIGTERM fails) does not pick a desktop
process instead.

**The `(^|/)` prefix and `$` suffix anchors:** The regex `(^|/)cc1plus$` matches
`/usr/lib/gcc/.../cc1plus` but not `cc1plus-background` or `my-cc1plus-tool`.
Anchors prevent partial matches from accidentally protecting or sacrificing
unintended processes.

## User Slice Memory Limit: MemoryMax=90%

Without a cgroupv2 memory limit on user.slice, a single user session can consume
all physical RAM plus all zRAM swap. When every page is exhausted, the kernel
has no headroom to run the OOM killer, flush dirty pages, or deliver signals —
the system enters an unbounded livelock where all processes are in D state
(uninterruptible sleep). This is the "desktop freeze" that persists until the
hardware watchdog resets the machine.

**90% not 100%:** Reserving 10% of physical RAM guarantees that the kernel,
systemd, and earlyoom always have allocatable memory even when the user session
exceeds its limit. The reserved pool is used for OOM killer page reclaim,
SIGTERM/SIGKILL signal delivery, page table allocation for the killing path,
dirty page writeback threads, and systemd emergency services. On a 32 GB
machine, 3.2 GB reserved is more than enough; on a 2 GB machine, 200 MB
suffices.

**Not lower than 90%:** If the limit is too strict (e.g., 50%), the user session
hits the cgroup OOM killer during normal workloads, killing the IDE or browser.
90% is a safety net for runaway processes, not an active limit during normal
operation.

**TasksMax=infinity:** The default TasksMax for user.slice is 33% of pids_max
(~10,000 on most systems). A power user running many apps (browser with
hundreds of tabs, IDE, language servers, containers) can exhaust this limit,
preventing fork() and exec() system calls — causing apparent freezes. Removing
the limit ensures the user can always spawn new processes.

## CARGO_BUILD_JOBS, MAKEFLAGS, NINJAJOBS = safe_core_limit

### Formula: max(1, vCPU - ceil(vCPU / 8))

A threshold at 4 vCPUs (reserve 1 core <=4, reserve 2 cores >4) creates a
discontinuity: a 4-core machine gets 3 build cores, a 5-core machine also gets
3. The universal formula smoothly reserves 1 core for every 8 available, with
a floor of 1. On a 4-core machine: ceil(4/8) = 1 reserved. On a 16-core: 2
reserved. On a 128-core: 16 reserved. The proportion of reserved cores decreases
as total cores increase (12.5% on large machines, 25-50% on small ones),
because desktop CPU needs grow sub-linearly with total cores.

Build tools default to all available CPUs. On a 16-core machine, 16 parallel
compile jobs may each use 1-2 GB of memory at peak, demanding 16-32 GB of
anonymous pages. The formula reserves enough cores for the desktop (window
manager, input, browser, editor) to stay responsive while dedicating the rest
to build throughput.

## NODE_OPTIONS --max-old-space-size = max(512, target_zram_mb * 0.5)

Node.js V8's garbage collector performs full GC (stop-the-world) when the old
space grows large. A full GC on an 8 GB heap can take seconds, freezing the
process. 50% of zRAM prevents Node from consuming the entire compressed swap
pool, leaving room for other processes. If zRAM is 16 GB, Node gets 8 GB max
heap.

**512 MB floor:** On a 2 GB RAM machine (zRAM = 2 GB), 50% gives Node 1 GB
max heap, which may trigger OOM within Node for large builds. The floor ensures
Node always has at least 512 MB regardless of zRAM size.
