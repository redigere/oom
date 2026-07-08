#!/usr/bin/env python3
import os
import sys
import glob

PROJECT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(PROJECT)

failures = 0


def fail(check: str, detail: str = ""):
    global failures
    failures += 1
    msg = f"FAIL {check}"
    if detail:
        msg += f" {detail}"
    sys.stderr.write(msg + "\n")


if os.path.isfile("HANDOFF.md"):
    fail("handoff_md_exists", "handoff must be a directory, not a flat file")

if not os.path.isdir("handoff"):
    fail("handoff_dir_missing")

handoff_files = sorted(glob.glob("handoff/*.yml"))
handoff_basenames = [os.path.basename(h) for h in handoff_files]

required_files = ["ci.yml", "kernel-baseline.yml", "remaining.yml", "role-splits.yml", "state.yml", "validation.yml"]
for rf in required_files:
    if rf not in handoff_basenames:
        fail("required_file_missing", rf)

if not os.path.isdir("handoff/_schemas"):
    fail("schemas_dir_missing")

schema_basenames = sorted(glob.glob("handoff/_schemas/*.yaml"))
schema_stems = {os.path.basename(s).replace(".schema.yaml", ".yml") for s in schema_basenames}

for hf in handoff_basenames:
    if hf not in schema_stems:
        fail("handoff_schema_missing", hf)

if failures:
    sys.stderr.write(f"FAIL {failures} violations\n")
    sys.exit(1)

print("PASS")
