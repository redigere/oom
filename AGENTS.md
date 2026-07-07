# AGENTS Context for AI Assistants — Why

## Commit Convention

Every commit MUST have exactly one subject line followed by a signed-off-by trailer.
No body, no multi-line messages. See DEV.md for format details.

### Signed-off-by Name Format

The sign-off name must be a real first and last name (e.g., `Alessio Attilio`),
not a single-word nickname, username, or bot handle. CI enforces at least
two whitespace-separated words before the email in the sign-off trailer.

## Why This Project Targets Debian, RedHat, and Archlinux

These three families cover ~95% of Linux developer workstations. Debian/Ubuntu for servers and laptops, Fedora/RHEL for enterprise workstations, Archlinux for enthusiasts. Each has different package names, service managers, and config paths for zRAM and OOM daemons. Supporting all three means the playbook runs unmodified on the vast majority of development machines.

## Why Localhost Only

The tuning modifies kernel parameters, swap devices, and system services that are per-machine. There is no remote target. Ansible's `connection=local` skips SSH overhead and allows `gather_facts` to read the real hardware directly.

## Why Roles Are Ordered and Coupled

system_discovery computes all tuning parameters from RAM and vCPU count — no hardcoded defaults. Consumed by 4 downstream roles:

| Fact | Formula | Consumed By | Rationale |
|------|---------|-------------|-----------|
| `system_discovery_target_zram_mb` | `max(2048, min(RAM_MB, 16384))` | zram_swap, dev_throttling | RAM-proportional zRAM with floor/cap |
| `system_discovery_safe_core_limit` | `max(1, vCPU − ceil(vCPU÷8))` | dev_throttling, thermal_throttling | Reserves ~1 core per 8 for desktop |
| `system_discovery_watermark_scale_factor` | `clamp(⌈500×8192÷RAM_MB⌉, 10, 1000)` | kernel_tuning | Keeps absolute reclaim zone ~constant |
| `system_discovery_earlyoom_min_free_pct` | `clamp(⌈40000÷RAM_MB⌉, 3, 10)` | oom_handler | Targets ~400MB absolute OOM trigger |
| `system_discovery_dirty_ratio` | `5` | kernel_tuning | Fixed percentage — caps writeback burst |
| `system_discovery_dirty_background_ratio` | `2` | kernel_tuning | Fixed percentage — starts early flusher |
| `system_discovery_min_free_kbytes` | `max(65536, RAM_MB×1024÷1000)` | kernel_tuning | Guarantees atomic allocation headroom |
| `system_discovery_admin_reserve_kbytes` | `max(4096, RAM_MB×1024÷4000)` | kernel_tuning | Root recovery headroom proportional to RAM |
| `system_discovery_user_reserve_kbytes` | `max(16384, RAM_MB×1024÷2000)` | kernel_tuning | User signal delivery headroom proportional to RAM |
| `system_discovery_compaction_proactiveness` | `clamp(20+60×4096÷RAM_MB, 20, 80)` | kernel_tuning | Inverse-RAM — small machines compact more |
| `system_discovery_page_lock_unfairness` | `1` | kernel_tuning | Minimum — fair reclaim under pressure |
| `system_discovery_zone_reclaim_mode` | `0` | kernel_tuning | Desktop — no NUMA zone preference |
| `system_discovery_reap_mem_on_sigkill` | `1` | kernel_tuning | Immediate memory reclaim on kill |
| `system_discovery_oom_dump_tasks` | `0` | kernel_tuning | Suppresses OOM dump for faster recovery |

All use continuous functions — no discrete thresholds, no hardcoded branches. This ensures `|X-Y|` (difference between ideal config and applied config) is minimized across every machine from 2 GB to 128 GB. The ordering is enforced by `playbook.yml`, not by `meta/main.yml`, because Ansible's dependency resolver evaluates meta dependencies at parse time, before runtime facts are available.

## Why No `|| true` or `|| echo` in Makefile Targets

Suppressing exit codes hides real failures. If `ansible-galaxy collection install ansible.posix` fails, the playbook should not run — it will fail with a module-not-found error that is harder to diagnose than a clean error from the install command. Every Makefile target either succeeds or prints its exit status. The `@` prefix is reserved for `echo` commands only, so non-echo commands show what they execute, making `make` output auditable.

## Why `become_ask_pass = False`

The playbook assumes passwordless sudo (NOPASSWD in /etc/sudoers). Asking for a sudo password in an automated playbook is disruptive: it breaks unattended runs, requires a terminal, and cannot be scripted. If passwordless sudo is not configured, the playbook fails immediately rather than prompting and then failing on the next task.

## Why Variable Names Are Prefixed With Role Name (ansible-lint rule)

Ansible's task runner evaluates variables in a flat namespace across all included files. Two roles might both `register: service_check` and clobber each other's state. Prefixing with the role name (e.g., `oom_handler_earlyoom_service_check`) guarantees uniqueness. This is an ansible-lint production profile requirement and prevents subtle bugs where a later task reads a variable registered by an unrelated role.

## Why cross-role variables Are Prefixed With system_discovery (e.g., `system_discovery_target_zram_mb`)

Facts set by system_discovery and consumed by other roles are prefixed with the source role name, not the consumer role name. This makes data provenance explicit: when reading `system_discovery_target_zram_mb` in zram_swap, it is clear that this value was computed by system_discovery. Renaming it per-role (e.g., `zram_swap_target_zram_mb`) would obscure the origin and require copying variables across roles.

## Why `changed_when: false` on read-only tasks

Tasks that inspect system state (e.g., `swapon --show`, `cat /sys/kernel/mm/lru_gen/enabled`) should never report "changed." They are polling commands. Without `changed_when: false`, Ansible reports them as changed every run because the command module always reports changed unless told otherwise. This creates false positives in dry-run output.

## Why `changed_when: true` on state-modifying shell/command tasks

Ansible's `command` and `shell` modules default to `changed_when: true` only when the command's output differs from a previous run (idempotency check). For tasks like `swapoff`, `update-grub`, and `echo 7 > /sys/kernel/mm/lru_gen/enabled`, the command always modifies state when it runs. Explicit `changed_when: true` ensures Ansible reports them as changed even on the first run.

## Why MGLRU Value Is Checked Before Writing

Writing to `/sys/kernel/mm/lru_gen/enabled` is cheap but not free (it triggers MMU notifiers). More importantly, without the check, Ansible reports "changed" every run because the shell module's output differs (the write always succeeds). Reading the current value and comparing avoids unnecessary writes and makes dry-run output truthful.

## Why GRUB Regex Uses `\bpsi=1\b`

The word boundary `\b` prevents `psi=1` from matching inside concatenated kernel parameters like `quiet_psi=1_splash`. GRUB configs may have arbitrary parameter ordering and concatenation; the regex must match `psi=1` as a standalone parameter. The backreference `\1` preserves all existing parameters and appends `psi=1`.

## Why systemd-oomd Is Found Via `find` (Not `systemctl`)

`systemctl` reports services in any state (including masked and disabled). Even a masked systemd-oomd returns success from `systemctl status`. Using `find` across standard systemd unit paths determines whether the unit file physically exists on disk, which is the correct check for "should I try to mask this?" rather than "is this service currently visible to systemd?"

## Why earlyoom Restart Checks Service Existence

Restarting a non-existent service causes `systemctl restart` to fail with exit code 5 (unit not found). Checking `LoadState != 'not-found'` before restart prevents this failure. The check is performed via `ansible.builtin.systemd` (not `stat` on the unit file) because earlyoom's unit may be installed by the package manager after the `package` task, and `systemd` module detects it only after `daemon_reload`.

## Why Ansible Lint Profile Is Production

The production profile includes rules for: variable name prefixing, FQCN for built-in modules, no `become` without `become_user`, no `ignore_errors`, no `failed_when`, no `shell` without justification. These rules enforce a baseline of correctness and auditability. The default profile (used by most projects) permits patterns that mask failures.

## Why Handoff Is a Directory Structure, Not a Flat File

The handoff system at `handoff/` replaces `HANDOFF.md` with a structured directory of YAML files, each with single-responsibility scope. This mirrors the role task split pattern: one file per concern, machine-readable and human-readable, validated by CI. `state.yml` captures implementation posture, `validation.yml` records validation results, `ci.yml` describes the CI landscape, `role-splits.yml` enumerates the task split structure, `remaining.yml` tracks pending work items, and `kernel-baseline.yml` tracks kernel version and feature state across CI runs. The old `HANDOFF.md` flat file is removed — a linear document cannot express the five orthogonal concerns that the directory structure captures.

## Why Handoff Has YAML Schema Enforcement

Every YAML file under `handoff/` has a corresponding schema in `handoff/_schemas/` that defines required keys and value types. Schemas are checked by two independent paths: `render.py` validates every file at display time, and `verify-structure.py` validates them in CI. This eliminates structural drift: adding a key to a YAML file without updating its schema causes a CI failure, and vice versa. Schemas use a lightweight YAML format (no external schema validator library) with recursive dict/list support, enforced by the `validate_schema()` function shared across both validators.

## Why handoff/render.py Replaces Makefile cat Commands

The previous `Makefile` `handoff` target listed each handoff file explicitly with `cat` and `@echo` — a hardcoded list that required editing when adding a new handoff file. `render.py` discovers `handoff/*.yml` at runtime via `glob`, validates each against its schema, and renders the file content. Adding a new handoff file now requires only creating the YAML file (and optionally a schema); `make handoff` includes it automatically. The `Makefile` target is a single `python3 handoff/render.py` call — no file list, no maintenance.

## Why kernel-baseline.yml Is Written via update-baseline.py, Not Shell Echo

The `kernel-bump.yml` workflow previously built `kernel-baseline.yml` using raw `echo` commands with string interpolation — fragile, untyped, and impossible to validate before writing. `update-baseline.py` reads a YAML dict from stdin, merges it into the existing baseline (preserving unspecified keys), and writes clean structured YAML. It also rejects unknown top-level keys, preventing silent misconfiguration. The script is invoked with a heredoc in CI, keeping the workflow readable while eliminating shell-based YAML generation.

## Why ansible_facts['*'] Instead of ansible_* Variables

Ansible 2.24 deprecates top-level `ansible_*` facts in favor of `ansible_facts['*']` dictionary access. This is a forward-compatibility change: future Ansible versions will remove the top-level names. Using `ansible_facts['os_family']` instead of `ansible_os_family` ensures the playbook works on both current and future Ansible without deprecation warnings.

## Why Zero Comments in Code

Comments rot. They drift from implementation, they excuse unclear code, and they add visual noise. Every piece of code must be self-documenting: function names, variable names, and structure must convey intent without inline annotations. This applies to every file in the repository: YAML tasks, Python scripts, shell snippets, Makefile recipes. A task name in Ansible is not a comment; it is structured metadata displayed during execution and is permitted. A `#` comment or a `"""docstring"""` in Python is forbidden.

## Why No Decorative Symbols in Output

Characters like `=`, `-`, `|`, `*` used purely as decoration (separator lines, ASCII tables, box drawings) add noise and break machine-parseability. Output must be pure log content: errors to stderr, pass/fail status to stdout, nothing else. A functional use of symbols in data (e.g., `cpu=4` in an error message) is acceptable because the symbol carries semantic meaning. A line consisting only of `=====` or `----` is not.

## Why Print Is Reserved for Logs

Printing to stdout or stderr is only for actionable log messages: violation reports, pass/fail status, or error diagnostics. Informational banners, summary tables, bounds ranges, and decorative status lines are not logs. If it does not help diagnose a failure or confirm success, do not print it. Violations go to stderr via `sys.stderr.write()`. Pass/fail goes to stdout via `print("PASS")` or `print("FAIL <count>")`. Detailed violation messages go to stderr only.

## Why No Em Dashes or Unicode Decorations

The em dash (—), bullet characters, arrows, box drawings, and any Unicode symbol used purely for decoration or visual separation are forbidden in all files: commit messages, task names, Python scripts, shell scripts, YAML, Makefiles, and handoff documents. Only ASCII printable characters (code points 32-126) are permitted in log output and commit subjects. Functional use of `-` as a list prefix or field separator is allowed because the character carries semantic meaning. A standalone `—` on a line or in a message is not.

## Why Conventional Commit Format Is Required

Every commit subject must match `type(optional-scope): subject` where type is one of `feat|fix|docs|style|refactor|perf|test|chore|ci|build|revert`. The subject starts with a lowercase letter. No em dashes, no colons outside the `type:` prefix. This format enables automated changelog generation, semantic versioning analysis, and commit-filtering CI jobs. Subject length should be under 72 characters.

## Why CI Scripts Write Violations to Stderr

When a validation script detects violations, each violation line is written to stderr via `sys.stderr.write()`. Only the summary line (`FAIL <count>` or `PASS`) goes to stdout. This separates diagnostics from status: stdout is machine-parseable (one word: PASS or FAIL), stderr carries human-readable details. The CI runner captures both streams and surfaces them in the job log.
