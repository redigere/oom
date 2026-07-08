#!/usr/bin/env python3
import json
import os
import glob
import sys

CONFIG_PATH = "/etc/thermal-throttling/config.json"
THROTTLED_MARKER = "THERMAL_THROTTLING_ACTIVE=1"
HYSTERESIS_MILLIDEGREES = 3000

IGNORED_ZONE_TYPES = {"ACPI Fan", "acpitz", "iwlwifi_1", "pch_cannonlake", "pch_cometlake", "pch_tigerlake", "INT3400 Thermal"}

try:
    with open(CONFIG_PATH) as f:
        config = json.load(f)
except OSError as e:
    sys.stderr.write(f"thermal_monitor: {CONFIG_PATH}: read error - {e}\n")
    sys.exit(1)
except json.JSONDecodeError as e:
    sys.stderr.write(f"thermal_monitor: {CONFIG_PATH}: invalid json - {e}\n")
    sys.exit(1)

try:
    threshold = int(config["temperature_threshold_millidegrees"])
    full_jobs = config["full_parallelism_jobs"]
    reduced_jobs = config["reduced_parallelism_jobs"]
    zone_glob = config["thermal_zone_glob"]
    profile_path = config["profile_d_path"]
except KeyError as e:
    sys.stderr.write(f"thermal_monitor: config missing key - {e}\n")
    sys.exit(1)

is_throttled = False
try:
    with open(profile_path) as pf:
        if THROTTLED_MARKER in pf.read():
            is_throttled = True
except OSError:
    pass

cool_threshold = threshold - HYSTERESIS_MILLIDEGREES

hot = False
for zone_path in sorted(glob.glob(zone_glob)):
    zone_dir = os.path.dirname(zone_path)
    zone_type_path = os.path.join(zone_dir, "type")
    try:
        with open(zone_type_path) as tf:
            zone_type = tf.read().strip()
        if zone_type in IGNORED_ZONE_TYPES:
            continue
    except OSError:
        pass

    try:
        with open(zone_path) as zf:
            raw = zf.read().strip()
    except OSError as e:
        sys.stderr.write(f"thermal_monitor: {zone_path}: {e}\n")
        continue
    try:
        temp = int(raw) if raw else 0
        active_threshold = cool_threshold if is_throttled else threshold
        if temp >= active_threshold:
            hot = True
            break
    except ValueError:
        sys.stderr.write(f"thermal_monitor: {zone_path}: non-numeric temp: {raw}\n")

if hot and not is_throttled:
    try:
        with open(profile_path, "w") as pf:
            pf.write(
                "export CARGO_BUILD_JOBS={}\n"
                "export MAKEFLAGS=-j{}\n"
                "export NINJAJOBS={}\n"
                "export {}\n".format(reduced_jobs, reduced_jobs, reduced_jobs, THROTTLED_MARKER)
            )
        os.chmod(profile_path, 0o644)
    except OSError as e:
        sys.stderr.write(f"thermal_monitor: {profile_path}: write error - {e}\n")
        sys.exit(1)

if not hot and is_throttled:
    try:
        with open(profile_path, "w") as pf:
            pf.write(
                "export CARGO_BUILD_JOBS={}\n"
                "export MAKEFLAGS=-j{}\n"
                "export NINJAJOBS={}\n".format(full_jobs, full_jobs, full_jobs)
            )
        os.chmod(profile_path, 0o644)
    except OSError as e:
        sys.stderr.write(f"thermal_monitor: {profile_path}: write error - {e}\n")
        sys.exit(1)
