#!/usr/bin/env python3
import time
import os
import signal
import sys

PSI_PATH = "/proc/pressure/memory"
STOP_THRESHOLD = 90.0
CONT_THRESHOLD = 60.0
POLL_INTERVAL = 2.0
PROTECTED_NAMES = {
    "gnome-shell", "plasma-desktop", "Xorg", "Xwayland", "kwin_wayland",
    "kwin_x11", "sway", "Hyprland", "pipewire", "pulseaudio", "systemd",
    "dbus-daemon", "earlyoom", "psi-monitor", "ssh", "sshd", "bash"
}

def get_memory_pressure():
    try:
        with open(PSI_PATH) as f:
            for line in f:
                if line.startswith("some"):
                    parts = line.split()
                    for p in parts:
                        if p.startswith("avg10="):
                            return float(p.split("=")[1])
    except OSError:
        pass
    return 0.0

def get_pids_to_stop(exclude_pids):
    max_rss = 0
    max_pid = -1
    target_name = ""
    for pid_str in os.listdir("/proc"):
        if not pid_str.isdigit():
            continue
        pid = int(pid_str)
        if pid in exclude_pids:
            continue
        try:
            with open(f"/proc/{pid}/status") as f:
                name = ""
                uid = 0
                for line in f:
                    if line.startswith("Name:"):
                        name = line.split()[1].strip()
                    elif line.startswith("Uid:"):
                        uid = int(line.split()[1])
            if uid == 0 or name in PROTECTED_NAMES:
                continue
            with open(f"/proc/{pid}/statm") as f:
                rss = int(f.read().split()[1])
                if rss > max_rss:
                    max_rss = rss
                    max_pid = pid
                    target_name = name
        except OSError:
            pass

    if max_pid == -1:
        return []

    pids_to_stop = []
    for pid_str in os.listdir("/proc"):
        if not pid_str.isdigit():
            continue
        pid = int(pid_str)
        if pid in exclude_pids:
            continue
        try:
            with open(f"/proc/{pid}/status") as f:
                name = ""
                uid = 0
                for line in f:
                    if line.startswith("Name:"):
                        name = line.split()[1].strip()
                    elif line.startswith("Uid:"):
                        uid = int(line.split()[1])
            if uid != 0 and name == target_name:
                pids_to_stop.append(pid)
        except OSError:
            pass

    return pids_to_stop

def main():
    stopped_pids = set()
    while True:
        pressure = get_memory_pressure()
        if pressure > STOP_THRESHOLD:
            pids = get_pids_to_stop(stopped_pids)
            for pid in pids:
                if pid != os.getpid():
                    try:
                        os.kill(pid, signal.SIGSTOP)
                        stopped_pids.add(pid)
                        sys.stderr.write(f"psi_monitor: stopped {pid} at {pressure}%\n")
                    except OSError:
                        pass
        elif pressure < CONT_THRESHOLD:
            for pid in list(stopped_pids):
                try:
                    os.kill(pid, signal.SIGCONT)
                    sys.stderr.write(f"psi_monitor: continued {pid} at {pressure}%\n")
                except OSError:
                    pass
                stopped_pids.remove(pid)
        sys.stdout.flush()
        sys.stderr.flush()
        time.sleep(POLL_INTERVAL)

if __name__ == "__main__":
    main()
