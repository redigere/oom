#!/usr/bin/env python3
import os
import sys
import re
import glob
import subprocess

PROJECT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(PROJECT)

failures = 0


def fail(check_name: str, detail: str = ""):
    global failures
    failures += 1
    msg = f"FAIL {check_name}"
    if detail:
        msg += f" {detail}"
    print(msg)


role_dirs = sorted(glob.glob("roles/*/"))
role_names = [os.path.basename(d.rstrip("/")) for d in role_dirs]
handoff_files = sorted(glob.glob("handoff/*.yml"))
handoff_basenames = [os.path.basename(h) for h in handoff_files]

if not role_names:
    fail("no_roles_found")
if not handoff_files:
    fail("no_handoff_files")

for rname in role_names:
    main_yml = f"roles/{rname}/tasks/main.yml"
    if not os.path.isfile(main_yml):
        fail(f"{rname}_main_exists")
    else:
        with open(main_yml) as f:
            if "import_tasks" not in f.read():
                fail(f"{rname}_main_uses_import")

    task_dir = f"roles/{rname}/tasks"
    if not os.path.isdir(task_dir):
        continue

    for root, _dirs, files in os.walk(task_dir):
        for fn in sorted(files):
            if not fn.endswith(".yml"):
                continue
            fpath = os.path.join(root, fn)
            with open(fpath) as f:
                for lineno, line in enumerate(f, 1):
                    comment_stripped = line.split("#")[0]

                    if re.search(r'ignore_errors:', comment_stripped):
                        fail(f"{rname}_ignore_errors", f"{fpath}:{lineno}")
                    if re.search(r'failed_when:', comment_stripped):
                        fail(f"{rname}_failed_when", f"{fpath}:{lineno}")

                    m = re.search(r'register:\s*(\w+)', comment_stripped)
                    if m:
                        varname = m.group(1)
                        if not varname.startswith(f"{rname}_") and not varname.startswith("system_discovery_"):
                            fail(f"{rname}_register_prefix", f"{varname} at {fpath}:{lineno}")

for rname in role_names:
    task_dir = f"roles/{rname}/tasks"
    if not os.path.isdir(task_dir):
        continue
    for root, _dirs, files in os.walk(task_dir):
        for fn in sorted(files):
            if not fn.endswith(".yml"):
                continue
            fpath = os.path.join(root, fn)
            with open(fpath) as f:
                content = f.read()
            if re.search(r"value:\s*'500'.*watermark_scale_factor|watermark_scale_factor.*value:\s*'500'", content):
                if 'system_discovery_watermark_scale_factor' not in content:
                    fail("kernel_tuning_hardcoded_wmsf", fpath)
            if re.search(r'-m\s+5(?:\s|$|")', content):
                if 'system_discovery_earlyoom_min_free_pct' not in content:
                    fail("oom_handler_hardcoded_m", fpath)

if not os.path.isfile("Makefile"):
    fail("makefile_missing")
else:
    with open("Makefile") as f:
        makefile_lines = f.readlines()

    for lineno, line in enumerate(makefile_lines, 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("@echo"):
            continue
        if stripped.startswith("@"):
            fail("makefile_at", f"line {lineno}")
        if re.search(r'\|\|\s*true(?:\s|$)', stripped):
            fail("makefile_true", f"line {lineno}")
        if "/dev/null" in stripped:
            fail("makefile_null", f"line {lineno}")

    phony_targets = []
    defined_targets = set()
    for line in makefile_lines:
        if line.startswith(".PHONY:"):
            phony_targets = line.replace(".PHONY:", "").strip().split()
        m = re.match(r'^([a-zA-Z_][a-zA-Z0-9_-]+):', line)
        if m:
            defined_targets.add(m.group(1))

    if not phony_targets:
        fail("makefile_phony_declared")
    else:
        for t in phony_targets:
            if t not in defined_targets:
                fail("phony_norecipe", t)

for hfile in handoff_basenames:
    fpath = os.path.join("handoff", hfile)
    if not os.path.isfile(fpath):
        fail(f"handoff_{hfile}_missing")
        continue
    with open(fpath) as f:
        try:
            import yaml
            data = yaml.safe_load(f)
        except Exception:
            fail(f"handoff_{hfile}_invalid_yaml")
            continue
    if data is None:
        fail(f"handoff_{hfile}_empty")
        continue
    if not isinstance(data, dict):
        fail(f"handoff_{hfile}_not_dict")
        continue
    if not data:
        fail(f"handoff_{hfile}_empty_dict")

if os.path.isfile("HANDOFF.md"):
    fail("handoff_md_exists")

kb_yml = "handoff/kernel-baseline.yml"
if os.path.isfile(kb_yml):
    with open(kb_yml) as f:
        try:
            import yaml
            kb = yaml.safe_load(f)
        except Exception:
            kb = None
    if not kb or not isinstance(kb, dict):
        fail("kernel_baseline_invalid")

if not os.path.isfile(".github/workflows/kernel-bump.yml"):
    fail("kernel_bump_workflow")

if os.path.isfile("Makefile"):
    makefile_text = "".join(makefile_lines)
    if "handoff" in makefile_text:
        if not re.search(r'^handoff:', makefile_text, re.MULTILINE):
            fail("handoff_makefile_target")
        if "handoff" not in (phony_targets or []):
            fail("handoff_phony_missing")

psi_yml = "roles/kernel_tuning/tasks/psi.yml"
if os.path.isfile(psi_yml):
    with open(psi_yml) as f:
        psi_content = f.read()
    if "stat" not in psi_content:
        fail("psi_no_bootloader_stat")

for scope, label in [("handoff/", "handoff"), (".", "root")]:
    try:
        result = subprocess.run(
            ["yamllint", "--strict", scope],
            capture_output=True, text=True
        )
        if result.returncode != 0:
            print(f"FAIL yamllint_{label}")
            for line in result.stdout.splitlines():
                print(f"  {line}")
            failures += 1
    except FileNotFoundError:
        pass

if failures:
    print(f"FAIL {failures} violations")
    sys.exit(1)

print("PASS")
