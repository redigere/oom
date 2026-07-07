# OOM Workstation Memory Tuning and OOM Eradication

## Why This Project Exists

Linux's default virtual memory and OOM behavior is tuned for server workloads: maximize throughput, avoid swapping, tolerate occasional OOM kills. This is wrong for development workstations.

On a dev machine, an OOM kill is not a minor stall — it destroys compiler state, wipes build caches, closes file descriptors, and costs minutes of rebuild time. A single `cargo build` or `ninja` invocation can balloon to 8-16 GB of anonymous pages. When the kernel OOM killer picks a victim, it often selects the IDE or terminal rather than the compiler, because the compiler has more pages and the kernel's heuristic avoids the "guilty" process.

Meanwhile, the default `vm.swappiness=60` tells the kernel to slightly prefer dropping file-backed page cache over swapping. On a workstation with abundant zRAM, this is backwards: page cache survives rebuilds and accelerates compilers; zRAM-compressed anonymous pages are cheap to swap. We want the kernel to swap *first* and keep page cache.

## Why zRAM Instead of Disk Swap

Disk swap is orders of magnitude slower than RAM. zRAM compresses anonymous pages in RAM with zstd, trading CPU cycles for effective memory density. A typical 32 GB machine can hold 50-60 GB of swap-equivalent content in 16 GB of zRAM under zstd. For a workstation that is mostly idle (waiting on the developer), the CPU cost of compression is negligible. For a machine that is under build load, zRAM prevents the latency cliff of disk I/O.

## Why zRAM Size = min(RAM, 16 GB)

Up to 8 GB RAM, the machine is memory-constrained; zRAM equal to full RAM gives the VM room to swap aggressively. Above 8 GB, marginal utility of more swap drops: build processes rarely need more than 16 GB of anonymous page headroom beyond what fits in free RAM. The cap prevents excessive CPU time spent compressing rarely-referenced pages.

## Why systemd-oomd Must Be Masked

systemd-oomd uses PSI pressure thresholds that fire too late for compiler workloads. By the time systemd-oomd acts, the machine is already thrashing. It also uses a recovery action (SIGTERM) that does not distinguish between critical and sacrificial processes. earlyoom is preferred because it acts earlier, on absolute free-memory and free-swap percentages, and because it allows explicit avoid/prefer regexes.

## Why earlyoom Avoid/Prefer Is Necessary

The kernel OOM killer's heuristic picks victims by oom_score, which roughly tracks memory usage. Build tools (compilers, linkers, bundlers) are the largest memory consumers on a dev machine, so the kernel tends to kill *them last*. But these are precisely the processes we *want* killed: they are stateless, restartable, and their memory can be reclaimed immediately. Desktop processes (shell, editor, DE, browser) are stateful and slow to restore. The avoid list protects UX-critical processes; the prefer list ensures memory-hungry ephemeral processes are sacrificed first.

## Why vm.swappiness = 100

This is the most controversial setting in the project. The conventional wisdom says "don't set swappiness above 60." The conventional wisdom assumes disk swap. zRAM changes the trade-off: swapping to zRAM is ~10x faster than disk swap and does not block I/O. Setting swappiness to 100 tells the kernel "prefer swap over page cache eviction in all cases." This retains file-backed pages in memory, which directly accelerates rebuilds (same header files, same object files, same libraries mapped repeatedly).

## Why vm.watermark_scale_factor = 500

Default watermark_scale_factor (10 = 0.1% of memory per watermark zone) means the kernel starts reclaiming very late. On a dev machine with bursty allocation patterns (`cargo build`, `node --build`, `ninja`), late reclaim causes latency spikes: the allocating process stalls waiting for pages. Raising it to 500 (5% per watermark) makes the kswapd thread reclaim earlier and more gradually, absorbing allocation bursts without blocking the faulting process. The cost is slightly more CPU time in reclaim, but on an idle-waiting-for-developer machine this is invisible.

## Why vm.vfs_cache_pressure = 50

The VFS cache (dentries, inodes) is critical for build performance. A C++ or Rust build opens and stats the same header files hundreds of times. Default vfs_cache_pressure (100) tells the kernel to reclaim VFS caches at the same rate as page cache. Reducing to 50 halves the reclaim rate, keeping filesystem metadata hot across build invocations. The cost is slightly more memory used for VFS objects, which is acceptable because zRAM absorbs anonymous page pressure.

## Why MGLRU = 7

Multi-Gen LRU replaces the kernel's single-list page reclaim algorithm with a multi-generational one that better handles mixed access patterns (long-lived processes like editors alongside short-lived build processes). Bitmask value 7 enables: 1 (MGLRU algorithm), 2 (page table walks for aging), 4 (proactive reclaim). Proactive reclaim (bit 4) is particularly useful on workstations: it scans PTEs in the background and reclaims cold pages before allocation pressure hits, avoiding direct reclaim stalls.

## Why PSI = 1

Pressure Stall Information is a kernel interface that tracks time spent waiting on memory, I/O, and CPU. earlyoom can use PSI metrics for memory pressure detection instead of purely free-memory thresholds. This is more accurate because it reflects actual stall time rather than raw free page counts. Without PSI, earlyoom falls back to /proc/meminfo heuristics, which can be misleading under zRAM (Committed_AS appears high even when most of it is compressed).

## Why Build Job Limits

Cargo, Make, and Ninja default to using all available CPUs for parallel jobs. On a development machine, this causes CPU contention with the editor, browser, terminal, and other interactive processes. The `safe_core_limit` formula reserves 1 core on machines with ≤4 vCPUs and 2 cores on machines with >4 vCPUs, ensuring the desktop stays responsive during builds. Node.js `--max-old-space-size` is set to 50% of zRAM because Node's garbage collector can trigger full GC at high heap sizes, causing latency spikes; limiting heap prevents Node from consuming the entire zRAM device.

## Why Roles Are Flat (No meta/main.yml Dependencies)

Ansible role dependencies (meta/main.yml) are evaluated before the playbook runs, which means they cannot depend on runtime facts set by previous roles. Since system_discovery sets facts consumed by zram_swap and dev_throttling, the dependency is purely ordering-based, enforced by the playbook's `roles:` list. Flat roles keep each role independently testable and make the execution order explicit in a single file.

## Why No Error Suppression

Ansible's default error handling masks failures: `ignore_errors: true` hides legitimate problems, `failed_when: false` turns runtime failures into silent skips. In a system-tuning context, a skipped task often means a parameter was not applied, which is worse than a loud failure because the symptom appears days later as an OOM event. Every task either succeeds or fails visibly.
