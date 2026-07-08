# OOM Workstation Memory Tuning and OOM Eradication

Linux's default VM and OOM behavior targets server workloads: maximize throughput, avoid swapping, tolerate occasional OOM kills. On development workstations this causes freezes and lost work.

The kernel OOM killer on dev machines often selects the IDE or terminal over the compiler, because the compiler has more pages and the heuristic avoids the "guilty" process. A single `cargo build` or `ninja` invocation can balloon to 8-16 GB of anonymous pages. Losing the editor to OOM destroys compiler state, wipes build caches, closes file descriptors, and costs minutes of rebuild time.

Default `vm.swappiness=60` treats page cache eviction and anonymous page swapping as equal cost. On a workstation with zRAM this is wrong: anonymous page swapping compresses with zstd (CPU-bound on both swapout and swapin), while page cache eviction is free — just drop the page. zRAM compression of application memory (editor buffers, browser tabs, language servers) causes visible stuttering on every context switch. swappiness is set aggressively low so the kernel drops page cache first and only swaps under genuine pressure.

## zRAM Instead of Disk Swap

Disk swap is orders of magnitude slower than RAM. zRAM compresses anonymous pages in RAM with zstd, trading CPU cycles for effective memory density. A typical 32 GB machine holds 50-60 GB of swap-equivalent content in 16 GB of zRAM under zstd. For a workstation idle-waiting on the developer, the CPU cost is negligible. Under build load, zRAM prevents the latency cliff of disk I/O.

## zRAM Size = min(RAM, 16 GB)

Up to 8 GB RAM, the machine is memory-constrained; zRAM equal to full RAM gives the VM room to swap aggressively. Above 8 GB, marginal utility of more swap drops: build processes rarely need more than 16 GB of anonymous page headroom beyond free RAM. The cap prevents excessive CPU time spent compressing rarely-referenced pages.

## systemd-oomd Must Be Masked

systemd-oomd uses PSI pressure thresholds that fire too late for compiler workloads — by the time it acts, the machine is already thrashing. It also uses SIGTERM indiscriminately without distinguishing critical from sacrificial processes. earlyoom replaces it because it acts earlier on absolute free-memory and free-swap percentages and supports explicit avoid/prefer regexes.

## earlyoom Avoid/Prefer

The kernel OOM killer's heuristic picks victims by oom_score, which roughly tracks memory usage. Build tools (compilers, linkers, bundlers) are the largest memory consumers on a dev machine, so the kernel tends to kill **them last**. But these are precisely the processes that should be killed: they are stateless, restartable, and their memory can be reclaimed immediately. Desktop processes (shell, editor, DE, browser) are stateful and slow to restore. The avoid list protects UX-critical processes; the prefer list ensures memory-hungry ephemeral processes are sacrificed first.

## vm.swappiness = 10

This is the most important setting for desktop fluidity. Conventional zRAM tuning says "set swappiness to 100 because zRAM is fast" — correct for throughput, wrong for interactivity. zRAM's zstd compression is CPU-bound: every page swapout compresses, every page swapin decompresses. On a desktop with many applications open, swappiness=100 forces the kernel to frequently compress and decompress application memory, stuttering on every context switch. swappiness=10 tells the kernel "strongly prefer dropping page cache over swapping anonymous pages," keeping application memory hot in physical RAM. Page cache is rebuilt from disk transparently; anonymous pages cannot be rebuilt from zRAM without CPU stalls. zRAM remains as a safety net for memory oversubscription, not as a primary reclaim target.

## vm.watermark_scale_factor = 500

Default watermark_scale_factor (10 = 0.1% of memory per watermark zone) means the kernel starts reclaiming very late. On a dev machine with bursty allocation patterns (`cargo build`, `node --build`, `ninja`), late reclaim causes latency spikes: the allocating process stalls waiting for pages. Raising to 500 (5% per watermark) makes kswapd reclaim earlier and more gradually, absorbing allocation bursts without blocking the faulting process. The cost is slightly more CPU time in reclaim, invisible on an idle-waiting-for-developer machine.

## vm.vfs_cache_pressure = 50

The VFS cache (dentries, inodes) is critical for build performance. A C++ or Rust build opens and stats the same header files hundreds of times. Default vfs_cache_pressure (100) tells the kernel to reclaim VFS caches at the same rate as page cache. Reducing to 50 halves the reclaim rate, keeping filesystem metadata hot across build invocations. The memory cost is acceptable because zRAM absorbs anonymous page pressure.

## MGLRU = 7

Multi-Gen LRU replaces the kernel's single-list page reclaim algorithm with multi-generational one that better handles mixed access patterns (long-lived processes like editors alongside short-lived build processes). Bitmask value 7 enables: 1 (MGLRU algorithm), 2 (page table walks for aging), 4 (proactive reclaim). Proactive reclaim (bit 4) scans PTEs in the background and reclaims cold pages before allocation pressure hits, avoiding direct reclaim stalls.

## PSI = 1

Pressure Stall Information tracks time spent waiting on memory, I/O, and CPU. earlyoom uses PSI metrics for memory pressure detection instead of purely free-memory thresholds. This is more accurate because it reflects actual stall time rather than raw free page counts. Without PSI, earlyoom falls back to /proc/meminfo heuristics, which mislead under zRAM because Committed_AS appears high even when most is compressed.

## Build Job Limits

Cargo, Make, and Ninja default to using all available CPUs for parallel jobs. On a development machine, this causes CPU contention with the editor, browser, terminal, and other interactive processes. The `safe_core_limit` formula reserves 1 core on machines with <=4 vCPUs and 2 cores on machines with >4 vCPUs, keeping the desktop responsive during builds. Node.js `--max-old-space-size` is set to 50% of zRAM because Node's garbage collector can trigger full GC at high heap sizes, causing latency spikes; limiting heap prevents Node from consuming the entire zRAM device.

## Roles and Ordering

The playbook runs seven roles in sequence: system_discovery, kernel_tuning, zram_swap, oom_handler, dev_throttling, thermal_throttling, screen_power. Each depends on data or state established by the preceding role. system_discovery first computes all hardware-derived facts (zRAM size, watermark factor, OOM thresholds, safe core limits) consumed by the other roles. kernel_tuning enables PSI and MGLRU before the OOM handler starts. zram_swap configures compressed swap before earlyoom measures swap usage. oom_handler starts earlyoom after PSI and zRAM are active. dev_throttling and thermal_throttling limit build parallelism after memory pressure characteristics are known. screen_power disables display blanking and DPMS last, as a desktop-experience capstone.

Flat roles (no meta/main.yml) keep each role independently testable and make the execution order explicit in a single file.

## No Error Suppression

Ansible's default error handling masks failures: `ignore_errors: true` hides legitimate problems, `failed_when: false` turns runtime failures into silent skips. In a system-tuning context, a skipped task often means a parameter was not applied — worse than a loud failure because the symptom appears days later as an OOM event. Every task either succeeds or fails visibly.
