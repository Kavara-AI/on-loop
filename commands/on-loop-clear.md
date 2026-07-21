---
name: on-loop-clear
description: Remove on-loop worktrees and optionally session records; never merge PRs
user_invocable: true
argument: "[--include-logs]"
---

# /on-loop:clear

Clean up on-loop worktrees and, when explicitly requested, session records. Cleanup does not merge or close PRs, delete remote branches, switch branches, or pull from a remote.

## Usage

```
/on-loop:clear                # Remove worktrees only; keep session records
/on-loop:clear --include-logs # Also delete session records after confirmation
```

## What This Does

1. Inspects session state and warns about active sessions and open PRs
2. Removes on-loop git worktrees under `.claude/worktrees/`
3. Marks abandoned active sessions as failed when records are retained
4. Optionally deletes `.on-loop/` session records after explicit confirmation

**Never merge a PR as a side effect of cleanup.** PR merge/close and remote branch deletion are separate, explicit user actions.

## Instructions

When this command is invoked:

1. **Validate arguments**:
   - Accept no arguments or exactly `--include-logs`.
   - Reject all other arguments without changing anything.

2. **Inspect before changing anything**:
   - Read `.on-loop/index.json` if it exists.
   - List active sessions, their worktree paths, and any `pr_url` values.
   - List registered worktrees with `git worktree list --porcelain`.
   - Identify only worktrees whose resolved paths are descendants of the repository's `.claude/worktrees/` directory. Do not remove the primary checkout or unrelated worktrees.
   - Warn that active sessions will be abandoned. Report linked PRs as untouched; do not query, merge, close, or modify them.

3. **Confirm destructive scope**:
   - Ask for explicit confirmation before removing worktrees when any active session or uncommitted worktree changes exist.
   - If `--include-logs` is present, separately state that `.on-loop/sessions/` and the session index will be deleted and require explicit confirmation.
   - If confirmation is declined or unavailable, stop without changing anything.

4. **Remove identified on-loop worktrees**:
   - For each verified path, first run `git status --short` in that worktree and report any uncommitted changes.
   - Remove the registered worktree with:
     ```bash
     git worktree remove <verified-worktree-path> --force
     ```
   - Run `git worktree prune` after removals.
   - Remove `.claude/worktrees/` only if it is empty. Never use an unverified slug in `rm -rf`.

5. **Update retained session records**:
   - Unless `--include-logs` was selected, update each removed worktree's active session to `status: "failed"` and set an error explaining that `/on-loop:clear` abandoned the worktree.
   - Leave complete and already-failed session records unchanged.

6. **Delete records only with `--include-logs`**:
   - After the separate confirmation, delete `.on-loop/sessions/` and reset or remove `.on-loop/index.json` as appropriate.
   - Preserve unrelated `.on-loop/` content, including `.on-loop/release-log.json`. The release record is outside this command's scope.

7. **Report**:
   - Worktrees removed and any failures
   - Active sessions marked failed
   - Whether session records were deleted
   - PR URLs left untouched
   - Current branch, explicitly noting that cleanup did not switch or update it

## Error Handling

- If a worktree path cannot be proven to be under `.claude/worktrees/`, skip it and report the path.
- If removal fails, report the worktree and stop before deleting records.
- Never merge or close a PR, delete a remote branch, switch branches, pull, or reset as recovery from a cleanup error.
