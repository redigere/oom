#!/usr/bin/env python3
import re
import sys
import subprocess

COMMIT_PATTERN = re.compile(
    r'^(?P<type>feat|fix|docs|style|refactor|perf|test|chore|ci|build|revert)'
    r'(?:\((?P<scope>[a-zA-Z0-9_.-]+)\))?'
    r':\s(?P<subject>.+)$'
)

failures = []

def get_commits():
    result = subprocess.run(
        ["git", "rev-list", "HEAD"],
        capture_output=True, text=True, check=True
    )
    return result.stdout.strip().splitlines()

def get_message(sha):
    result = subprocess.run(
        ["git", "log", "-1", "--format=%B", sha],
        capture_output=True, text=True, check=True
    )
    return result.stdout

for sha in get_commits():
    msg = get_message(sha)
    lines = msg.strip().splitlines()
    subject = lines[0].strip()
    trailers = lines[1:] if len(lines) > 1 else []

    m = COMMIT_PATTERN.match(subject)
    if not m:
        failures.append(
            f"commit {sha[:7]} — subject does not follow conventional commit format:\n"
            f"  expected: type(scope): subject\n"
            f"  got:      {subject}"
        )
        continue

    if len(lines) > 2 and any(t.strip() for t in lines[1:-1]):
        failures.append(
            f"commit {sha[:7]} — body lines found, only signoff allowed:\n"
            f"  {subject}"
        )

    sob = [t for t in trailers if t.startswith("Signed-off-by:")]
    if not sob:
        failures.append(
            f"commit {sha[:7]} — missing Signed-off-by trailer:\n"
            f"  {subject}"
        )

if failures:
    for f in failures:
        print(f"FAIL {f}")
    print(f"\nFAIL {len(failures)} violation(s)")
    sys.exit(1)

print("PASS")
