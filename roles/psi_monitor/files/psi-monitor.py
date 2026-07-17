#!/usr/bin/env python3
import time
import os
import signal
import sys

import yaml

CONFIG_PATH = "/etc/psi-monitor/config.yml"
with open(CONFIG_PATH) as f:
    config = yaml.safe_load(f)

PSI_MEMORY_PATH = config["psi_memory_path"]
PSI_IO_PATH = config["psi_io_path"]
STOP_THRESHOLD = config["stop_threshold"]
CONT_THRESHOLD = config["cont_threshold"]
IO_STOP_THRESHOLD = config["io_stop_threshold"]
IO_CONT_THRESHOLD = config["io_cont_threshold"]
POLL_INTERVAL = config["poll_interval"]
PROTECTED_NAMES = set(config["protected_names"])
BOUNDARY_NAMES = set(config["boundary_names"])

LAST_TOTAL = 0
LAST_TIME = 0.0
LAST_IO_TOTAL = 0
LAST_IO_TIME = 0.0

def get_instant_pressure(path, last_total, last_time):
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
    return last_total, last_time, 0.0

def get_process_info():
    processes = {}
    for pid_str in os.listdir("/proc"):
        if not pid_str.isdigit():
            continue
        pid = int(pid_str)
        with open(f"/proc/{pid}/stat") as f:
            parts = f.read().split(") ")
            if len(parts) >= 2:
                name = parts[0].split("(")[1]
                ppid = int(parts[1].split()[1])
                processes[pid] = {"name": name, "ppid": ppid, "rss": 0}
        with open(f"/proc/{pid}/statm") as f:
            processes[pid]["rss"] = int(f.read().split()[1])
    return processes

def get_tree_pids(processes, exclude_pids):
    return []

def main():
    global LAST_TOTAL, LAST_TIME, LAST_IO_TOTAL, LAST_IO_TIME
    stopped_pids = set()
    while True:
        LAST_TOTAL, LAST_TIME, mem_pressure = get_instant_pressure(
            PSI_MEMORY_PATH, LAST_TOTAL, LAST_TIME)
        LAST_IO_TOTAL, LAST_IO_TIME, io_pressure = get_instant_pressure(
            PSI_IO_PATH, LAST_IO_TOTAL, LAST_IO_TIME)

        if mem_pressure > STOP_THRESHOLD:
            procs = get_process_info()
            pids = get_tree_pids(procs, stopped_pids)
            for pid in pids:
                if pid != os.getpid():
                    os.kill(pid, signal.SIGSTOP)
                    stopped_pids.add(pid)
                    sys.stderr.write(
                        f"psi_monitor: stopped {pid} "
                        f"({procs.get(pid, {}).get('name', 'unknown')}) "
                        f"mem={mem_pressure:.1f}% io={io_pressure:.1f}%\n")
        elif mem_pressure < CONT_THRESHOLD:
            for pid in list(stopped_pids):
                os.kill(pid, signal.SIGCONT)
                sys.stderr.write(
                    f"psi_monitor: continued {pid} "
                    f"mem={mem_pressure:.1f}% io={io_pressure:.1f}%\n")
                stopped_pids.remove(pid)
        sys.stdout.flush()
        sys.stderr.flush()
        time.sleep(POLL_INTERVAL)

if __name__ == "__main__":
    main()
