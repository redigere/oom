#!/usr/bin/env python3
import os
import sys
import re
import glob
import subprocess

PROJECT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(PROJECT)

try:
    import yaml
except ImportError:
    sys.stderr.write("FAIL missing_dependency: PyYAML not installed\n")
    sys.exit(1)

failures = 0


def fail(check_name: str, detail: str = ""):
    global failures
    failures += 1
    msg = f"FAIL {check_name}"
    if detail:
        msg += f" {detail}"
    print(msg)


def safe_read(path):
    try:
        with open(path) as f:
            return f.read()
    except OSError as e:
        fail(f"read_error", f"{path}: {e}")
        return None


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
        content = safe_read(main_yml)
        if content and "import_tasks" not in content:
            fail(f"{rname}_main_uses_import")

    task_dir = f"roles/{rname}/tasks"
    if not os.path.isdir(task_dir):
        continue

    for root, _dirs, files in os.walk(task_dir):
        for fn in sorted(files):
            if not fn.endswith(".yml"):
                continue
            fpath = os.path.join(root, fn)
            content = safe_read(fpath)
            if content is None:
                continue
            for lineno, line in enumerate(content.splitlines(), 1):
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
            content = safe_read(fpath)
            if content is None:
                continue
            if re.search(r"value:\s*'500'.*watermark_scale_factor|watermark_scale_factor.*value:\s*'500'", content):
                if 'system_discovery_watermark_scale_factor' not in content:
                    fail("kernel_tuning_hardcoded_wmsf", fpath)
            if re.search(r'-m\s+5(?:\s|$|")', content):
                if 'system_discovery_earlyoom_min_free_pct' not in content:
                    fail("oom_handler_hardcoded_m", fpath)

makefile_lines = None
if not os.path.isfile("Makefile"):
    fail("makefile_missing")
else:
    content = safe_read("Makefile")
    if content is None:
        makefile_lines = []
    else:
        makefile_lines = content.splitlines(keepends=True)

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

TYPE_CHECKERS = {
    str: lambda v: isinstance(v, str),
    bool: lambda v: isinstance(v, bool),
    int: lambda v: isinstance(v, int),
    list: lambda v: isinstance(v, list),
    dict: lambda v: isinstance(v, dict),
}

TYPE_NAMES = {
    str: "str",
    bool: "bool",
    int: "int",
    list: "list",
    dict: "dict",
}


def validate_schema(data, schema, path=""):
    for key in schema.get("required", []):
        if key not in data:
            fail(f"schema_{path}{key}: missing required key")
    for key, props in schema.get("properties", {}).items():
        if key not in data:
            continue
        val = data[key]
        expected = props.get("type")
        if expected:
            checker = TYPE_CHECKERS.get(expected)
            if checker and not checker(val):
                fail(f"schema_{path}{key}: expected {TYPE_NAMES.get(expected, expected)}, got {type(val).__name__}")
        if expected == dict and isinstance(val, dict):
            nested = {k: v for k, v in props.items() if k in ("required", "properties")}
            if nested:
                validate_schema(val, nested, f"{path}{key}.")
        if expected == list and isinstance(val, list):
            item_schema = props.get("items")
            if item_schema:
                for idx, item in enumerate(val):
                    if isinstance(item, dict):
                        validate_schema(item, item_schema, f"{path}{key}[{idx}].")


SCHEMAS = "handoff/_schemas"

for hfile in handoff_basenames:
    fpath = os.path.join("handoff", hfile)
    if not os.path.isfile(fpath):
        fail(f"handoff_{hfile}_missing")
        continue
    content = safe_read(fpath)
    if content is None:
        continue
    try:
        data = yaml.safe_load(content)
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
    schema_path = os.path.join(SCHEMAS, hfile)
    if os.path.isfile(schema_path):
        content = safe_read(schema_path)
        if content is None:
            continue
        try:
            schema = yaml.safe_load(content)
        except Exception:
            fail(f"handoff_{hfile}_invalid_schema")
            continue
        if schema and isinstance(schema, dict):
            validate_schema(data, schema)

if os.path.isfile("HANDOFF.md"):
    fail("handoff_md_exists")

kb_yml = "handoff/kernel-baseline.yml"
if os.path.isfile(kb_yml):
    content = safe_read(kb_yml)
    if content:
        try:
            kb = yaml.safe_load(content)
        except Exception as e:
            fail("kernel_baseline_parse_error", str(e))
            kb = None
        if not kb or not isinstance(kb, dict):
            fail("kernel_baseline_invalid")

if not os.path.isfile(".github/workflows/kernel-bump.yml"):
    fail("kernel_bump_workflow")

if makefile_lines is not None:
    makefile_text = "".join(makefile_lines)
    if "handoff" in makefile_text:
        if not re.search(r'^handoff:', makefile_text, re.MULTILINE):
            fail("handoff_makefile_target")
        if "handoff" not in (phony_targets or []):
            fail("handoff_phony_missing")

psi_yml = "roles/kernel_tuning/tasks/psi.yml"
if os.path.isfile(psi_yml):
    content = safe_read(psi_yml)
    if content and "stat" not in content:
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
        print(f"FAIL yamllint_{label} binary not found in PATH")
        failures += 1

if failures:
    print(f"FAIL {failures} violations")
    sys.exit(1)

print("PASS")
