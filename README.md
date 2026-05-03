# Commit Curator

A Python CLI tool that automates cherry-picking GitLab commits from `dev_r4` onto a fresh UAT branch by ticket number, handles conflict resolution via VS Code, then opens a Merge Request automatically.

---

## Requirements

- Python 3.10+
- Git (in PATH)
- VS Code (`code` command in PATH)
- A GitLab Personal Access Token with `api` scope

---

## Setup

```bash
# 1. Install dependency
pip install requests

# 2. Add your GitLab PAT
# Open .env and replace the placeholder:
GITLAB_TOKEN=glpat-xxxxxxxxxxxx
```

> `.env` is gitignored — never commit it.

---

## Usage

```bash
python curator.py SLA-2132
python curator.py SLA-2132 SLA-2145 SLA-2190
```

---

## What It Does

1. **Prompts for UAT branch name** — defaults to `uat/uat_r4/YYYYMMDD`, fully editable
2. **Fetches origin** and searches `dev_r4` for commits matching each ticket (oldest-first)
3. **Shows a preview** of all commits to be picked — waits for your confirmation
4. **Creates a fresh branch** off `origin/dev_r4`
5. **Cherry-picks one commit at a time**:
   - ✅ Clean apply → moves on automatically
   - ⚠️ Conflict → opens VS Code, blocks until you close it
     - Conflicts resolved → continues automatically
     - Conflicts still present → **aborts entire operation**, exits
6. **Pushes** the branch to origin
7. **Creates a Merge Request** to `uat_r4` via GitLab API and prints the MR URL

---

## Configuration

Edit `config.json` to change branches or project — no script changes needed:

```json
{
  "source_branch": "dev_r4",
  "target_branch": "uat_r4",
  "gitlab_url": "git.tsp.dev",
  "project_path": "sla-leap/leap-web"
}
```

| Key | Description |
|---|---|
| `source_branch` | Branch to search commits from |
| `target_branch` | Branch the MR will target |
| `gitlab_url` | GitLab host (no `https://`) |
| `project_path` | `namespace/repo-name` |

---

## Conflict Resolution Guide

When VS Code opens during a conflict:

1. Go to **Source Control** (Ctrl+Shift+G)
2. Open each file marked with `C` (conflict)
3. Use **Accept Current / Incoming / Both** or edit manually
4. Once all conflicts are resolved, the files will auto-stage when you close VS Code
5. **Close VS Code** — the script continues automatically

> If you close VS Code without resolving everything, the script will detect remaining conflicts and abort cleanly.

---

## File Structure

```
commit-curator/
  curator.py        # main script
  config.json       # branch + project config (safe to commit)
  .env              # GitLab PAT — NEVER commit this
  .gitignore        # excludes .env
  requirements.txt  # requests
  README.md
  CLAUDE.md         # context for AI-assisted development
```
