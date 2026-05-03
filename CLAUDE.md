# Commit Curator — Claude Context

## What This Project Is

A single-file Python CLI tool that automates the UAT deployment cherry-pick process for the `sla-leap/leap-web` GitLab project. Developers run it with ticket numbers; it handles everything from finding commits to opening a MR.

## Project Layout

```
curator.py        # entire tool — all logic lives here
config.json       # runtime config (branches, gitlab url, project path)
.env              # GITLAB_TOKEN only — gitignored
requirements.txt  # requests only
```

## Architecture Decisions

- **Single file** (`curator.py`) — intentional. This is a dev utility, not a library. Keep it that way unless complexity forces a split.
- **No Click/Typer** — plain `sys.argv` + `input()` to avoid extra dependencies.
- **`GIT_EDITOR=true`** injected into subprocess env to suppress any editor pop-ups during cherry-pick.
- **`code --wait .`** blocks the script at the OS level — VS Code must be fully closed to resume.
- **`git add -A` before `--continue`** — safe because the user resolved everything in VS Code; staging manually in VS Code's Source Control panel is optional.
- **Conflict detection via `git status --porcelain`** — checks for `UU`, `AA`, `DD`, `AU`, `UA`, `DU`, `UD` prefixes, not just non-zero exit codes.

## Key Functions

| Function | Purpose |
|---|---|
| `find_commits(ticket, source_ref)` | `git log --grep` oldest-first, returns `[(sha, subject)]` |
| `has_unresolved_conflicts()` | Parses porcelain status for unmerged markers |
| `open_vscode_blocking()` | `code --wait .` — blocks until VS Code window closes |
| `create_mr(...)` | POST to GitLab API `/api/v4/projects/:id/merge_requests` |
| `abort_and_exit(msg)` | Runs `git cherry-pick --abort` then exits — always call on failure mid-pick |

## Config Shape

```json
{
  "source_branch": "dev_r4",
  "target_branch": "uat_r4",
  "gitlab_url": "git.tsp.dev",
  "project_path": "sla-leap/leap-web"
}
```

## Default UAT Branch Name

`uat/{target_branch}/{YYYYMMDD}` — e.g. `uat/uat_r4/20260503`

User is prompted to confirm or override before anything runs.

## Behaviours to Preserve

- Always fetch before searching commits
- Always confirm commit list before creating the branch
- Check for existing local branch before `git checkout -b` — exit with clear message if found
- On conflict: open VS Code → check again after close → if still dirty, abort entire operation
- MR failure is non-fatal: print manual URL and exit with code 1 (branch already pushed)

## Common Extension Points

- **Add a `--dry-run` flag** — skip branch creation/push/MR, just print what would happen
- **Add `--base` override** — let user specify a different base ref instead of `origin/{source_branch}`
- **Support multiple configs** — accept `--config path/to/config.json` for teams with multiple environments
- **Slack/Teams notification** — post MR URL after creation
- **Log file** — write cherry-pick results to `curator-YYYYMMDD.log` for audit trail
