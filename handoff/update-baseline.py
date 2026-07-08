#!/usr/bin/env python3
import os
import sys
import yaml

HANDOFF = os.path.dirname(os.path.abspath(__file__))
BASELINE = os.path.join(HANDOFF, "kernel-baseline.yml")

try:
    data = yaml.safe_load(sys.stdin)
except Exception as e:
    sys.stderr.write(f"stdin: yaml parse error - {e}\n")
    sys.exit(1)

if not isinstance(data, dict):
    sys.stderr.write("stdin: expected YAML dict\n")
    sys.exit(1)

allowed = {"current_kernel", "previous_kernel", "first_detected", "features", "sysctl_defaults", "validation"}
for key in data:
    if key not in allowed:
        sys.stderr.write(f"{key}: unknown key\n")
        sys.exit(1)

if os.path.isfile(BASELINE):
    try:
        with open(BASELINE) as f:
            existing = yaml.safe_load(f)
    except Exception as e:
        sys.stderr.write(f"baseline: read error - {e}\n")
        sys.exit(1)
    if not isinstance(existing, dict):
        existing = {}
else:
    existing = {}

for key, val in data.items():
    if isinstance(val, dict) and isinstance(existing.get(key), dict):
        existing[key].update(val)
    else:
        existing[key] = val

try:
    with open(BASELINE, "w") as f:
        f.write("---\n")
        yaml.dump(existing, f, default_flow_style=False, sort_keys=False, allow_unicode=True)
except OSError as e:
    sys.stderr.write(f"baseline: write error - {e}\n")
    sys.exit(1)
