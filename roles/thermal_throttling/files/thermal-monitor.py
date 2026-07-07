#!/usr/bin/env python3
import json
import os
import glob
import sys

CONFIG_PATH = "/etc/thermal-throttling/config.json"
THROTTLED_MARKER = "THERMAL_THROTTLING_ACTIVE=1"

with open(CONFIG_PATH) as f:
    config = json.load(f)

threshold = config["temperature_threshold_millidegrees"]
full_jobs = config["full_parallelism_jobs"]
reduced_jobs = config["reduced_parallelism_jobs"]
zone_glob = config["thermal_zone_glob"]
profile_path = config["profile_d_path"]

hot = False
for zone_path in glob.glob(zone_glob):
    try:
        with open(zone_path) as zf:
            raw = zf.read().strip()
    except OSError as e:
        sys.stderr.write(f"thermal_monitor: {zone_path}: {e}\n")
        continue
    try:
        if raw and int(raw) >= threshold:
            hot = True
            break
    except ValueError:
        sys.stderr.write(f"thermal_monitor: {zone_path}: non-numeric temp: {raw}\n")

is_throttled = False
if os.path.isfile(profile_path):
    with open(profile_path) as pf:
        if THROTTLED_MARKER in pf.read():
            is_throttled = True

if hot and not is_throttled:
    with open(profile_path, "w") as pf:
        pf.write(
            "export CARGO_BUILD_JOBS={}\n"
            "export MAKEFLAGS=-j{}\n"
            "export NINJAJOBS={}\n"
            "export {}\n".format(reduced_jobs, reduced_jobs, reduced_jobs, THROTTLED_MARKER)
        )

if not hot and is_throttled:
    with open(profile_path, "w") as pf:
        pf.write(
            "export CARGO_BUILD_JOBS={}\n"
            "export MAKEFLAGS=-j{}\n"
            "export NINJAJOBS={}\n".format(full_jobs, full_jobs, full_jobs)
        )
