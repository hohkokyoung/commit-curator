#!/usr/bin/env python3
"""
Commit Curator — cherry-pick UAT deployments by ticket number.

Usage:
    python curator.py SLA-2132 SLA-2145 SLA-2190
"""

import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

try:
    import requests
except ImportError:
    print("ERROR: Run  pip install requests  first.")
    sys.exit(1)

ROOT = Path(__file__).parent
CONFIG_PATH = ROOT / "config.json"
ENV_PATH = ROOT / ".env"

# ── helpers ──────────────────────────────────────────────────────────────────

def load_config() -> dict:
    with open(CONFIG_PATH) as f:
        return json.load(f)


def load_env() -> dict:
    env = {}
    if ENV_PATH.exists():
        for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    return env


REPO_PATH: str = ""


def run(cmd: str, check=True, capture=False) -> subprocess.CompletedProcess:
    result = subprocess.run(
        cmd, shell=True, capture_output=capture, text=True,
        cwd=REPO_PATH or None,
    )
    if check and result.returncode != 0:
        raise RuntimeError(f"Command failed: {cmd}\n{(result.stderr or '').strip()}")
    return result


def git(cmd: str, **kwargs) -> subprocess.CompletedProcess:
    return run(f"git {cmd}", **kwargs)


def has_unresolved_conflicts() -> bool:
    result = git("status --porcelain", capture=True)
    conflict_prefixes = {"UU", "AA", "DD", "AU", "UA", "DU", "UD"}
    for line in result.stdout.splitlines():
        if len(line) >= 2 and line[:2] in conflict_prefixes:
            return True
    return False


def find_commits(ticket: str, source_ref: str) -> list[tuple[str, str]]:
    """Return [(sha, subject), ...] oldest-first for commits matching ticket."""
    result = git(
        f'log {source_ref} --grep="{ticket}" --format="%H|%s" --reverse',
        capture=True,
    )
    commits = []
    for line in result.stdout.splitlines():
        line = line.strip()
        if line:
            sha, _, subject = line.partition("|")
            commits.append((sha.strip(), subject.strip()))
    return commits


def open_vscode_blocking():
    """Open VS Code in the repo directory and block until the window closes."""
    run(f'code --wait "{REPO_PATH}"', check=False)


def create_mr(
    gitlab_url: str,
    project_path: str,
    token: str,
    source_branch: str,
    target_branch: str,
    tickets: list[str],
    picked: list[tuple[str, str, str]],
) -> str:
    encoded = project_path.replace("/", "%2F")
    url = f"https://{gitlab_url}/api/v4/projects/{encoded}/merge_requests"

    title = f"UAT Deploy: {', '.join(tickets)}"
    lines = ["## Cherry-picked commits", ""]
    for ticket, sha, msg in picked:
        lines.append(f"- `{sha[:8]}` [{ticket}] {msg}")
    description = "\n".join(lines)

    resp = requests.post(
        url,
        headers={"PRIVATE-TOKEN": token},
        json={
            "source_branch": source_branch,
            "target_branch": target_branch,
            "title": title,
            "description": description,
            "remove_source_branch": False,
        },
        timeout=30,
    )

    if resp.status_code not in (200, 201):
        raise RuntimeError(f"GitLab API error {resp.status_code}: {resp.text}")

    return resp.json()["web_url"]


def banner(text: str, char="─"):
    width = 62
    print(char * width)
    print(f"  {text}")
    print(char * width)


def abort_and_exit(message: str, code=1):
    print(f"\n  ERROR: {message}")
    git("cherry-pick --abort", check=False)
    sys.exit(code)

# ── main ─────────────────────────────────────────────────────────────────────

def main():
    if len(sys.argv) < 2:
        print("Usage: python curator.py SLA-2132 SLA-2145 ...")
        sys.exit(1)

    tickets = [t.upper() for t in sys.argv[1:]]

    global REPO_PATH

    config = load_config()
    env = load_env()

    source_branch: str = config.get("source_branch", "dev_r4")
    target_branch: str = config.get("target_branch", "uat_r4")
    gitlab_url: str = config.get("gitlab_url", "git.tsp.dev")
    project_path: str = config.get("project_path", "sla-leap/leap-web")
    repo_path: str = config.get("repo_path", "")

    if not repo_path:
        print("ERROR: Set 'repo_path' in config.json to your local leap-web repo path.")
        sys.exit(1)
    if not Path(repo_path).is_dir():
        print(f"ERROR: repo_path '{repo_path}' does not exist.")
        sys.exit(1)
    REPO_PATH = repo_path

    token = env.get("GITLAB_TOKEN", "")
    if not token or token == "your_pat_here":
        print("ERROR: Set GITLAB_TOKEN in .env before running.")
        sys.exit(1)

    default_branch = f"uat/{target_branch}/{datetime.today().strftime('%Y%m%d')}"
    try:
        user_input = input(f"UAT branch name [{default_branch}]: ").strip()
    except KeyboardInterrupt:
        print("\nCancelled.")
        sys.exit(0)
    uat_branch = user_input if user_input else default_branch

    print()
    banner("Commit Curator", "═")
    print(f"  Tickets : {', '.join(tickets)}")
    print(f"  Source  : {source_branch}")
    print(f"  UAT     : {uat_branch}  →  MR to {target_branch}")
    banner("", "═")
    print()

    # ── 1. Fetch ──────────────────────────────────────────────────────────────
    print("[1/5] Fetching origin...")
    git("fetch origin")

    source_ref = f"origin/{source_branch}"

    # ── 2. Find commits ───────────────────────────────────────────────────────
    print(f"[2/5] Searching {source_branch} for commits...\n")
    all_commits: list[tuple[str, str, str]] = []  # (ticket, sha, subject)

    for ticket in tickets:
        commits = find_commits(ticket, source_ref)
        if not commits:
            print(f"  {ticket}: no commits found — skipping")
        else:
            print(f"  {ticket}: {len(commits)} commit(s)")
            for sha, msg in commits:
                print(f"    {sha[:8]}  {msg}")
                all_commits.append((ticket, sha, msg))

    if not all_commits:
        print("\nNothing to cherry-pick. Aborting.")
        sys.exit(1)

    print()
    try:
        input("Press ENTER to start cherry-pick, or Ctrl+C to cancel... ")
    except KeyboardInterrupt:
        print("\nCancelled.")
        sys.exit(0)

    # ── 3. Create UAT branch ──────────────────────────────────────────────────
    print(f"\n[3/5] Creating {uat_branch} from {source_ref}...")

    existing = git("branch --list " + uat_branch, capture=True).stdout.strip()
    if existing:
        print(f"  ERROR: Branch '{uat_branch}' already exists locally.")
        print("  Delete it first:  git branch -D " + uat_branch)
        sys.exit(1)

    # Stash any local changes so checkout doesn't get blocked
    stash_result = git("stash push -m 'curator-autostash'", capture=True)
    stashed = "No local changes" not in stash_result.stdout

    git(f"checkout -b {uat_branch} {source_ref}")

    if stashed:
        print("  Restoring stashed local changes...")
        git("stash pop")

    # ── 4. Cherry-pick ────────────────────────────────────────────────────────
    print(f"\n[4/5] Cherry-picking {len(all_commits)} commit(s)...\n")

    for i, (ticket, sha, msg) in enumerate(all_commits, 1):
        prefix = f"  [{i}/{len(all_commits)}]"
        print(f"{prefix} {sha[:8]}  [{ticket}]  {msg}")

        env_no_editor = {**os.environ, "GIT_EDITOR": "true"}
        result = subprocess.run(
            f"git cherry-pick {sha}",
            shell=True,
            capture_output=True,
            text=True,
            env=env_no_editor,
        )

        if result.returncode == 0:
            print(f"{'':>{len(prefix)}}  ✓ Clean")
            continue

        if not has_unresolved_conflicts():
            abort_and_exit(
                f"cherry-pick failed for {sha[:8]} (unexpected):\n  {result.stderr.strip()}"
            )

        print(f"{'':>{len(prefix)}}  ! CONFLICT — opening VS Code")
        print(f"{'':>{len(prefix)}}    Resolve all conflicts, stage your files,")
        print(f"{'':>{len(prefix)}}    then CLOSE VS Code to continue.\n")

        open_vscode_blocking()

        if has_unresolved_conflicts():
            abort_and_exit(
                f"Conflicts still present after VS Code closed ({sha[:8]} [{ticket}]).\n"
                "  Resolve all conflict markers and try again."
            )

        # Stage everything the dev resolved and continue
        git("add -A")
        subprocess.run(
            "git cherry-pick --continue --no-edit",
            shell=True,
            env=env_no_editor,
        )
        print(f"{'':>{len(prefix)}}  ✓ Conflict resolved\n")

    # ── 5. Push + MR ─────────────────────────────────────────────────────────
    print(f"[5/5] Pushing {uat_branch}...")
    git(f"push origin {uat_branch}")

    print(f"      Creating MR → {target_branch}...")
    try:
        mr_url = create_mr(
            gitlab_url, project_path, token,
            uat_branch, target_branch,
            tickets, all_commits,
        )
    except RuntimeError as exc:
        print(f"\n  WARNING: Branch pushed but MR creation failed:\n  {exc}")
        print(f"  Create the MR manually at https://{gitlab_url}/{project_path}/-/merge_requests/new")
        sys.exit(1)

    print()
    banner("Done!", "═")
    print(f"  MR: {mr_url}")
    banner("", "═")
    print()


if __name__ == "__main__":
    main()
