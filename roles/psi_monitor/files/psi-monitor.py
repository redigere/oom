#!/usr/bin/env python3
import time
import os
import signal
import sys

import yaml

CONFIG_PATH = "/etc/psi-monitor/config.yml"

try:
    with open(CONFIG_PATH) as f:
        config = yaml.safe_load(f)
except OSError as e:
    sys.stderr.write(f"psi_monitor: cannot read config {CONFIG_PATH}: {e}\n")
    sys.exit(1)
except yaml.YAMLError as e:
    sys.stderr.write(f"psi_monitor: invalid config {CONFIG_PATH}: {e}\n")
    sys.exit(1)

PSI_MEMORY_PATH = config.get("psi_memory_path", "/proc/pressure/memory")
STOP_THRESHOLD = config.get("stop_threshold", 25.0)
CONT_THRESHOLD = config.get("cont_threshold", 8.0)
POLL_INTERVAL = config.get("poll_interval", 0.3)

LAST_TOTAL = 0
LAST_TIME = 0.0


def get_instant_pressure(path, last_total, last_time):
    try:
        with open(path) as f:
            for line in f:
                if line.startswith("some"):
                    parts = line.split()
                    for p in parts:
                        if p.startswith("total="):
                            total = int(p.split("=")[1])
                            now = time.time()
                            if last_time == 0.0:
                                return total, now, 0.0
                            dt = now - last_time
                            if dt <= 0:
                                return total, now, 0.0
                            delta_us = total - last_total
                            pressure = (delta_us / 1000000.0) / dt * 100.0
                            return total, now, min(100.0, max(0.0, pressure))
    except (OSError, ValueError):
        pass
    return last_total, last_time, 0.0


def get_process_info():
    processes = {}
    try:
        pids = os.listdir("/proc")
    except OSError:
        return processes
    for pid_str in pids:
        if not pid_str.isdigit():
            continue
        pid = int(pid_str)
        try:
            with open(f"/proc/{pid}/stat") as f:
                parts = f.read().split(") ")
                if len(parts) >= 2:
                    name = parts[0].split("(")[1]
                    ppid = int(parts[1].split()[1])
                    processes[pid] = {"name": name, "ppid": ppid, "rss": 0}
            with open(f"/proc/{pid}/statm") as f:
                processes[pid]["rss"] = int(f.read().split()[1])
        except (OSError, ValueError, IndexError):
            pass
    return processes


def get_tree_pids(processes, root_pid):
    descendants = [root_pid]
    added = True
    while added:
        added = False
        for pid, info in processes.items():
            if info["ppid"] in descendants and pid not in descendants:
                descendants.append(pid)
                added = True
    return descendants


def main():
    global LAST_TOTAL, LAST_TIME
    stopped_pids = set()
    while True:
        try:
            LAST_TOTAL, LAST_TIME, mem_pressure = get_instant_pressure(
                PSI_MEMORY_PATH, LAST_TOTAL, LAST_TIME)

            if mem_pressure > STOP_THRESHOLD:
                procs = get_process_info()
                max_rss = 0
                max_pid = -1
                for pid, info in procs.items():
                    if pid == os.getpid() or pid in stopped_pids:
                        continue
                    if info["rss"] > max_rss:
                        max_rss = info["rss"]
                        max_pid = pid
                if max_pid > 1:
                    tree = get_tree_pids(procs, max_pid)
                    for pid in tree:
                        if pid != os.getpid() and pid not in stopped_pids:
                            try:
                                os.kill(pid, signal.SIGSTOP)
                                stopped_pids.add(pid)
                                sys.stderr.write(
                                    f"psi_monitor: stopped {pid} "
                                    f"({procs.get(pid, {}).get('name', 'unknown')}) "
                                    f"mem={mem_pressure:.1f}%\n")
                            except OSError:
                                pass
            elif mem_pressure < CONT_THRESHOLD:
                for pid in list(stopped_pids):
                    try:
                        os.kill(pid, signal.SIGCONT)
                        sys.stderr.write(
                            f"psi_monitor: continued {pid} "
                            f"mem={mem_pressure:.1f}%\n")
                    except OSError:
                        pass
                    stopped_pids.discard(pid)
        except Exception as e:
            sys.stderr.write(f"psi_monitor: loop error: {e}\n")
        sys.stdout.flush()
        sys.stderr.flush()
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
