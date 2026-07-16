#!/usr/bin/env python3
import time
import os
import signal
import sys

PSI_MEMORY_PATH = "/proc/pressure/memory"
PSI_IO_PATH = "/proc/pressure/io"
STOP_THRESHOLD = 25.0
CONT_THRESHOLD = 8.0
IO_STOP_THRESHOLD = 40.0
IO_CONT_THRESHOLD = 15.0
POLL_INTERVAL = 0.3
PROTECTED_NAMES = {
    "gnome-shell", "plasma-desktop", "Xorg", "Xwayland", "kwin_wayland",
    "kwin_x11", "sway", "Hyprland", "pipewire", "pulseaudio", "systemd",
    "dbus-daemon", "earlyoom", "psi-monitor", "ssh", "sshd", "bash",
    "gdm3", "gdm", "mutter",
    "firefox", "chrome", "chromium", "brave", "vivaldi", "opera", "msedge",
    "code", "vscode", "codium", "idea", "pycharm", "webstorm", "clion",
    "phpstorm", "rubymine", "rider", "goland", "eclipse", "netbeans",
    "sublime_text", "gedit", "kate", "mousepad", "leafpad", "xed",
    "obsidian", "discord", "slack", "teams", "zoom", "skype",
    "gnome-terminal", "konsole", "alacritty", "kitty", "wezterm", "xterm"
}

LAST_TOTAL = 0
LAST_TIME = 0.0
LAST_IO_TOTAL = 0
LAST_IO_TIME = 0.0

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
    except OSError:
        pass
    return last_total, last_time, 0.0

BOUNDARY_NAMES = {
    "bash", "zsh", "fish", "sh", "dash", "tmux", "screen", "sshd", "systemd",
    "gnome-terminal-", "konsole", "alacritty", "kitty", "wezterm", "xterm",
    "init", "kthreadd", "dbus-daemon", "earlyoom", "psi-monitor", "login",
    "su", "sudo", "pkexec"
}

def get_process_info():
    processes = {}
    for pid_str in os.listdir("/proc"):
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
        except OSError:
            pass
    return processes

def get_tree_pids(processes, exclude_pids):
    max_rss = 0
    max_pid = -1

    for pid, info in processes.items():
        if pid in exclude_pids or info["name"] in PROTECTED_NAMES:
            continue
        if info["rss"] > max_rss:
            max_rss = info["rss"]
            max_pid = pid

    if max_pid == -1:
        return []

    current = max_pid
    root_pid = max_pid

    while True:
        if current not in processes:
            break
        ppid = processes[current]["ppid"]
        if ppid not in processes or ppid == 0 or ppid == 1:
            break
        p_name = processes[ppid]["name"]
        is_boundary = False
        for b in BOUNDARY_NAMES:
            if b in p_name:
                is_boundary = True
                break
        if is_boundary or p_name in PROTECTED_NAMES:
            break
        root_pid = ppid
        current = ppid

    descendants = [root_pid]
    added = True
    while added:
        added = False
        for pid, info in processes.items():
            if info["ppid"] in descendants and pid not in descendants:
                if pid not in exclude_pids:
                    descendants.append(pid)
                    added = True

    return descendants

def main():
    global LAST_TOTAL, LAST_TIME, LAST_IO_TOTAL, LAST_IO_TIME
    stopped_pids = set()
    while True:
        LAST_TOTAL, LAST_TIME, mem_pressure = get_instant_pressure(
            PSI_MEMORY_PATH, LAST_TOTAL, LAST_TIME)
        LAST_IO_TOTAL, LAST_IO_TIME, io_pressure = get_instant_pressure(
            PSI_IO_PATH, LAST_IO_TOTAL, LAST_IO_TIME)

        if mem_pressure > STOP_THRESHOLD or io_pressure > IO_STOP_THRESHOLD:
            procs = get_process_info()
            pids = get_tree_pids(procs, stopped_pids)
            for pid in pids:
                if pid != os.getpid():
                    try:
                        os.kill(pid, signal.SIGSTOP)
                        stopped_pids.add(pid)
                        sys.stderr.write(
                            f"psi_monitor: stopped {pid} "
                            f"({procs.get(pid, {}).get('name', 'unknown')}) "
                            f"mem={mem_pressure:.1f}% io={io_pressure:.1f}%\n")
                    except OSError:
                        pass
        elif mem_pressure < CONT_THRESHOLD and io_pressure < IO_CONT_THRESHOLD:
            for pid in list(stopped_pids):
                try:
                    os.kill(pid, signal.SIGCONT)
                    sys.stderr.write(
                        f"psi_monitor: continued {pid} "
                        f"mem={mem_pressure:.1f}% io={io_pressure:.1f}%\n")
                except OSError:
                    pass
                stopped_pids.remove(pid)
        sys.stdout.flush()
        sys.stderr.flush()
        time.sleep(POLL_INTERVAL)

if __name__ == "__main__":
    main()
