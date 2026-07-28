#!/usr/bin/env python3
"""
Regression guard for the bug where post-robotics-news.yml committed
index.html + posted.json but forgot pending.json, silently discarding every
in-flight approval draft. Both workflows write to these state files and must
git-add all of them in their commit step, or state written by the Python
scripts never survives past the ephemeral runner.

Run: python tests/test_workflow_state_files.py
"""
import os
import re
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORKFLOWS_DIR = os.path.join(REPO_ROOT, ".github", "workflows")

REQUIRED_STATE_FILES = {
    "scripts/pending.json",
    "scripts/posted.json",
    "scripts/tg_offset.json",
    "scripts/pending_companies.json",
}

# tg_offset.json is only touched by check-approvals.yml (it owns the getUpdates
# offset), so post-robotics-news.yml is exempt from that one file.
EXEMPTIONS = {
    "post-robotics-news.yml": {"scripts/tg_offset.json"},
}

WORKFLOWS_TO_CHECK = ["post-robotics-news.yml", "check-approvals.yml"]


def git_add_lines(workflow_path):
    with open(workflow_path) as f:
        content = f.read()
    return re.findall(r"^\s*git add (.+)$", content, re.MULTILINE)


def main():
    failures = []

    for name in WORKFLOWS_TO_CHECK:
        path = os.path.join(WORKFLOWS_DIR, name)
        if not os.path.exists(path):
            failures.append(f"{name}: workflow file not found at {path}")
            continue

        add_lines = git_add_lines(path)
        if not add_lines:
            failures.append(f"{name}: no 'git add' line found in commit step")
            continue

        staged = set()
        for line in add_lines:
            staged.update(line.split())

        required = REQUIRED_STATE_FILES - EXEMPTIONS.get(name, set())
        missing = required - staged

        if missing:
            failures.append(f"{name}: commit step is missing {sorted(missing)} from 'git add' — state written to these files will be silently lost")

    if failures:
        print("FAILED:")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)

    print(f"OK: all {len(WORKFLOWS_TO_CHECK)} workflows stage their required state files.")


if __name__ == "__main__":
    main()
