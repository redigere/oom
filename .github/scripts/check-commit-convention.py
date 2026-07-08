#!/usr/bin/env python3
import re
import sys
import subprocess

COMMIT_PATTERN = re.compile(
    r'^(?P<type>feat|fix|docs|style|refactor|perf|test|chore|ci|build|revert)'
    r'(?:\((?P<scope>[a-zA-Z0-9_.-]+)\))?'
    r':\s(?P<subject>.+)$'
)

SOB_PATTERN = re.compile(
    r'^Signed-off-by:\s+(?P<name>.+?)\s+<(?P<email>[^>]+)>$'
)

failures = []


def get_commits():
    try:
        result = subprocess.run(
            ["git", "rev-list", "HEAD"],
            capture_output=True, text=True, check=True
        )
        return result.stdout.strip().splitlines()
    except subprocess.CalledProcessError as e:
        sys.stderr.write(f"git rev-list failed (exit {e.returncode}): {e.stderr.strip()}\n")
        sys.exit(1)
    except OSError as e:
        sys.stderr.write(f"git not found: {e}\n")
        sys.exit(1)


def get_message(sha):
    try:
        result = subprocess.run(
            ["git", "log", "-1", "--format=%B", sha],
            capture_output=True, text=True, check=True
        )
        return result.stdout
    except subprocess.CalledProcessError as e:
        sys.stderr.write(f"git log {sha[:7]} failed (exit {e.returncode}): {e.stderr.strip()}\n")
        sys.exit(1)
    except OSError as e:
        sys.stderr.write(f"git not found: {e}\n")
        sys.exit(1)


for sha in get_commits():
    msg = get_message(sha)
    lines = msg.strip().splitlines()
    subject = lines[0].strip() if lines else ""
    trailers = lines[1:] if len(lines) > 1 else []

    if not subject:
        failures.append(
            f"commit {sha[:7]}: empty subject"
        )
        continue

    m = COMMIT_PATTERN.match(subject)
    if not m:
        failures.append(
            f"commit {sha[:7]}: subject not conventional\n"
            f"  expected: type(scope): subject\n"
            f"  got:      {subject}"
        )
        continue

    if len(lines) > 2 and any(t.strip() for t in lines[1:-1]):
        failures.append(
            f"commit {sha[:7]}: body found, only signoff allowed\n"
            f"  {subject}"
        )

    sob = [t for t in trailers if t.startswith("Signed-off-by:")]
    if not sob:
        failures.append(
            f"commit {sha[:7]}: missing Signed-off-by\n"
            f"  {subject}"
        )
    else:
        sm = SOB_PATTERN.match(sob[0])
        if not sm:
            failures.append(
                f"commit {sha[:7]}: invalid sign-off format\n"
                f"  expected: Signed-off-by: Firstname Lastname <email>\n"
                f"  got:      {sob[0]}"
            )
        elif len(sm.group('name').split()) < 2:
            failures.append(
                f"commit {sha[:7]}: sign-off name must be firstname lastname\n"
                f"  got:      {sm.group('name')}"
            )

if failures:
    for f in failures:
        sys.stderr.write(f"FAIL {f}\n")
    print(f"FAIL {len(failures)}")
    sys.exit(1)

print("PASS")
