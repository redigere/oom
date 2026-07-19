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
    sys.stderr.write(f"psi_monitor: cannot read {CONFIG_PATH}: {e}\n")
    sys.exit(1)
except yaml.YAMLError as e:
    sys.stderr.write(f"psi_monitor: invalid yaml {CONFIG_PATH}: {e}\n")
    sys.exit(1)

for key in ("psi_memory_path", "stop_threshold", "cont_threshold", "poll_interval"):
    if key not in config:
        sys.stderr.write(f"psi_monitor: missing config key {key}\n")
        sys.exit(1)

PSI_PATH = config["psi_memory_path"]
STOP = config["stop_threshold"]
CONT = config["cont_threshold"]
INTERVAL = config["poll_interval"]


def read_pressure(path, prev_total, prev_time):
    try:
        with open(path) as f:
            for line in f:
                if line.startswith("some"):
                    for token in line.split():
                        if token.startswith("total="):
                            total = int(token.split("=")[1])
                            now = time.time()
                            if prev_time == 0.0:
                                return total, now, 0.0
                            dt = now - prev_time
                            if dt <= 0:
                                return total, now, 0.0
                            pct = ((total - prev_total) / 1_000_000) / dt * 100
                            return total, now, max(0.0, min(100.0, pct))
    except (OSError, ValueError):
        pass
    return prev_total, prev_time, 0.0


def scan_processes():
    procs = {}
    try:
        entries = os.listdir("/proc")
    except OSError:
        return procs
    for name in entries:
        if not name.isdigit():
            continue
        pid = int(name)
        try:
            with open(f"/proc/{pid}/stat") as f:
                text = f.read()
            comm_end = text.rfind(")")
            if comm_end < 0:
                continue
            fields = text[comm_end + 2:].split()
            ppid = int(fields[1])
            with open(f"/proc/{pid}/statm") as f:
                rss = int(f.read().split()[0])
            procs[pid] = {"ppid": ppid, "rss": rss}
        except (OSError, ValueError, IndexError):
            pass
    return procs


def walk_tree(procs, root):
    family = [root]
    grew = True
    while grew:
        grew = False
        for pid, info in procs.items():
            if info["ppid"] in family and pid not in family:
                family.append(pid)
                grew = True
    return family


def main():
    prev_total = 0
    prev_time = 0.0
    frozen = set()
    while True:
        try:
            prev_total, prev_time, pressure = read_pressure(
                PSI_PATH, prev_total, prev_time)

            if pressure > STOP:
                procs = scan_processes()
                best_rss = 0
                best_pid = -1
                me = os.getpid()
                for pid, info in procs.items():
                    if pid == me or pid in frozen:
                        continue
                    if info["rss"] > best_rss:
                        best_rss = info["rss"]
                        best_pid = pid
                if best_pid > 1:
                    for pid in walk_tree(procs, best_pid):
                        if pid != me and pid not in frozen:
                            try:
                                os.kill(pid, signal.SIGSTOP)
                                frozen.add(pid)
                                sys.stderr.write(
                                    f"psi_monitor: stopped {pid} "
                                    f"mem={pressure:.1f}%\n")
                            except OSError:
                                pass
            elif pressure < CONT:
                for pid in list(frozen):
                    try:
                        os.kill(pid, signal.SIGCONT)
                        sys.stderr.write(
                            f"psi_monitor: continued {pid} "
                            f"mem={pressure:.1f}%\n")
                    except OSError:
                        pass
                    frozen.discard(pid)
        except Exception as e:
            sys.stderr.write(f"psi_monitor: {e}\n")
        sys.stdout.flush()
        sys.stderr.flush()
        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
