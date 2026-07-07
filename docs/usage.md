# Usage — Why

## Why `make check` Before `make run`

`ansible-playbook --check` performs a dry-run: Ansible connects to localhost, gathers facts, evaluates all `when` conditions, and reports what would change — without making any changes. This is critical because the playbook:

- Modifies GRUB configuration, which requires `update-grub` and a reboot to take effect
- Disables and removes disk swap entries from /etc/fstab, which is irreversible without manual editing
- Installs packages (zram-tools, earlyoom) via the system package manager
- Stops and masks systemd-oomd, which may be providing OOM protection that you rely on

A dry-run reveals all of these changes before they are applied, giving you the opportunity to audit the diff and abort if anything is unexpected.

## Why `make status` After `make run`

The verification commands in `make status` check that every subsystem is active after the playbook completes. This catches silent failures: a package that was not installed (earlyoom missing), a service that did not start (zramswap inactive), a kernel parameter that was not applied (swappiness still at 60). Each line prints both the value and the exit status — if a file or service is missing, the error is visible rather than silently ignored.

## Why `make run` Depends on `make setup`

The playbook requires `ansible.posix.sysctl` (for the sysctl loop), `ansible.builtin.systemd`, and `ansible.builtin.package` (community.general). The `ansible.posix` collection is not included in the default Ansible installation on any distribution. Without it, the sysctl tasks fail silently or with a confusing module-not-found error. Running `setup` first ensures all collections are present before the playbook executes.

## Why the Playbook Runs Against localhost

The tuning parameters (swappiness, watermark_scale_factor, vfs_cache_pressure, MGLRU, zRAM, earlyoom) are system-wide and affect every process. They must be applied on the machine where the developer works. Running against localhost with `gather_facts: true` lets Ansible read the actual hardware configuration (RAM, CPU, OS family) and compute tuning values tailored to that specific machine. This makes the playbook portable — the same repo works on a 4 GB laptop and a 64 GB workstation.

## Why GRUB Changes Require a Reboot

PSI (`psi=1`) is a kernel command-line parameter. The kernel reads it once at boot; there is no runtime interface to enable PSI after the system is running. Because the playbook modifies `/etc/default/grub` and runs `update-grub`, the change is staged for the next boot. Until the next reboot, earlyoom runs without PSI support and falls back to /proc/meminfo heuristics.

## Why MGLRU Changes Are Immediate (No Reboot)

MGLRU is toggled via `/sys/kernel/mm/lru_gen/enabled`, which is a writable sysfs file. Writing `7` takes effect immediately in the running kernel. The tmpfiles.d entry (`/etc/tmpfiles.d/mglru.conf`) only persists the value across reboots; the initial application is at runtime. No reboot is needed.

## Why sysctl Changes Are Immediate

`ansible.posix.sysctl` with `reload: true` runs `sysctl -p` after writing the config file. The parameters take effect immediately in the running kernel. The file `/etc/sysctl.d/99-oom-tuning.conf` persists them across reboots.

## Why Rollback Is Manual (Not Automated)

The modification set is small and well-defined: 3 sysctl files, 1 tmpfiles entry, 1 GRUB config, 1 zRAM config, 1 earlyoom config, 1 profile script. Automated rollback is more dangerous than manual rollback because:
1. It requires tracking which changes were made in the current run versus pre-existing state
2. A failed automated rollback leaves the system in a partially-reverted state that is harder to diagnose than a clean reversion
3. The `clean` Makefile target removes all config files and disables services, giving a clean baseline for reapplication

Manual rollback is intentionally explicit: remove config file, revert sysctl at runtime, update-grub if needed, restart original service. Each step is visible and auditable.

## Why `make clean` Does Not Re-enable systemd-oomd

The playbook intentionally masks systemd-oomd. Unmasking and re-enabling it would restore the OOM behavior this project was created to replace. If you want systemd-oomd back, you must explicitly unmask it with `systemctl unmask systemd-oomd && systemctl enable --now systemd-oomd`. This deliberate friction ensures you do not accidentally revert OOM policy.

## Why Tags Are Not Used

Ansible tags allow running a subset of roles or tasks. They are omitted here because:
- Roles are tightly coupled via facts: running dev_throttling without system_discovery fails because the facts are undefined
- Kernel tuning (PSI GRUB change) requires a reboot to take effect; running only oom_handler without PSI enabled degrades earlyoom accuracy
- The playbook is short (5 roles, ~15 tasks total); filtering is unnecessary complexity

If isolation is needed, `ansible-playbook --start-at-task` or `ansible-playbook --tags` can be added per user request.
