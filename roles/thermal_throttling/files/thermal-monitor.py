#!/usr/bin/env python3
import yaml
import os
import glob
import sys

CONFIG_PATH = "/etc/thermal-throttling/config.yml"
THROTTLED_MARKER = "THERMAL_THROTTLING_ACTIVE=1"
HYSTERESIS_MILLIDEGREES = 3000

IGNORED_ZONE_TYPES = {"ACPI Fan", "acpitz", "iwlwifi_1", "pch_cannonlake", "pch_cometlake", "pch_tigerlake", "INT3400 Thermal"}

with open(CONFIG_PATH) as f:
    config = yaml.safe_load(f)

threshold = int(config["temperature_threshold_millidegrees"])
full_jobs = config["full_parallelism_jobs"]
reduced_jobs = config["reduced_parallelism_jobs"]
zone_glob = config["thermal_zone_glob"]
profile_path = config["profile_d_path"]

is_throttled = False
with open(profile_path) as pf:
    if THROTTLED_MARKER in pf.read():
        is_throttled = True

cool_threshold = threshold - HYSTERESIS_MILLIDEGREES

hot = False
for zone_path in sorted(glob.glob(zone_glob)):
    zone_dir = os.path.dirname(zone_path)
    zone_type_path = os.path.join(zone_dir, "type")
    
    with open(zone_type_path) as tf:
        zone_type = tf.read().strip()
    if zone_type in IGNORED_ZONE_TYPES:
        continue

    with open(zone_path) as zf:
        raw = zf.read().strip()

    temp = int(raw) if raw else 0
    active_threshold = cool_threshold if is_throttled else threshold
    if temp >= active_threshold:
        hot = True
        break

if hot and not is_throttled:
    with open(profile_path, "w") as pf:
        pf.write(
            "export CARGO_BUILD_JOBS={}\n"
            "export MAKEFLAGS=-j{}\n"
            "export NINJAJOBS={}\n"
            "export {}\n".format(reduced_jobs, reduced_jobs, reduced_jobs, THROTTLED_MARKER)
        )
    os.chmod(profile_path, 0o644)

if not hot and is_throttled:
    with open(profile_path, "w") as pf:
        pf.write(
            "export CARGO_BUILD_JOBS={}\n"
            "export MAKEFLAGS=-j{}\n"
            "export NINJAJOBS={}\n".format(full_jobs, full_jobs, full_jobs)
        )
    os.chmod(profile_path, 0o644)
