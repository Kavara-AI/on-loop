---
name: on-continue
description: Guide one roadmap step through the agent-prompt workflow
user_invocable: true
argument: feature slug (optional -- auto-detects if only one roadmap exists)
---

# /on-continue

This workflow command instructs Claude Code to read roadmap state, select one eligible step, record an advisory lock, and guide it through coding, test, security, and review prompts.

## Usage

```
/on-continue                  # auto-detect feature, pick next step
/on-continue <feature-slug>   # specify which feature
```

Each session uses its own git worktree, but the current JSON read/write lock protocol is not atomic across Claude Code processes. Until executable coordination is added, run only one roadmap-writing `/on-continue` session per feature at a time.

## Instructions

When this command is invoked:

### 1. Initialize Session

1. Generate a session ID (UUID v4): `python3 -c "import uuid; print(str(uuid.uuid4()))"`
2. Generate a session name: `YYYYMMDD_HHMMSS_<branch-slug>` (e.g., `20260426_143052_feature-slug-phase-1`)
3. Store both for the duration of this execution

### 2. Identify the Roadmap

Same logic as `/on-plan`:
- If slug provided, use it
- If not, auto-detect from `roadmap/.state/`
- If none found, suggest `/on-prepare`

### 3. Read State and Find Next Step

Following the `skills/roadmap-state/SKILL.md` "Identify Next Step" algorithm:

1. Read `roadmap/.state/<feature-slug>.json`
2. Read `roadmap/.state/_global.json`
3. Identify the current phase
4. If the current phase is complete, advance to the next non-complete phase
5. Within the phase, find the first eligible step:
   - Status is `not-started` (or `failed` -- can be retried)
   - Not `exclusive` while other steps are in-progress
   - No `conflicts_with` steps are in-progress
   - No file-level overlap with locked files
6. If no step is available:
   - If steps are `in-progress` (other sessions working), report "All available steps are currently in progress. Try again later or run `/on-pause` in other sessions."
   - If all steps are `complete` in all phases, report "Feature complete! All steps in all phases are done."
   - If steps are `blocked`, report which steps are blocked and why

### 4. Acquire Lock

Following `skills/roadmap-lock/SKILL.md`:

1. Check for stale locks on the target step (heartbeat > 10 min old)
2. If stale, reclaim it (log warning)
3. Write lock entry in the feature state file
4. Register session in `_global.json`
5. Verify lock with read-after-write
6. If lock acquisition fails (race condition), back off and try the next eligible step

### 5. Create Git Worktree

Create an isolated worktree for this step's execution:

1. Determine the branch for this phase from the roadmap state (e.g., `feature/<slug>-phase-<N>`)
2. Create branch if it doesn't exist: `git branch <branch-name>` (from current HEAD or phase base)
3. Create worktree: `git worktree add .claude/worktrees/<branch-slug> <branch-name>`
4. If the worktree already exists (e.g., from a prior failed attempt), reuse it

### 6. Set Up Session Directory

Create the session directory for this step's execution:

1. Create `.on-loop/sessions/<session-name>/` with `agent-notes/` subdirectory
2. Write `.on-loop/sessions/<session-name>/state.json` with:
   - `version`: `"1.1"`
   - `session_id`: the generated UUID
   - `phase`: `"CODE"` (the step starts at code since the roadmap IS the spec/plan)
   - `prompt`: The step's description from the roadmap
   - `branch`: the branch name
   - `worktree_path`: `.claude/worktrees/<branch-slug>`
   - `session_dir`: `.on-loop/sessions/<session-name>`
   - `waivers`: `[]`
   - Context: phase title, step number, feature name
3. Write `.on-loop/sessions/<session-name>/plan.md` with:
   - The step's detailed description from the roadmap
   - Files to create/modify
   - Acceptance criteria from the phase
   - Any relevant context from other completed steps
4. Create empty `.on-loop/sessions/<session-name>/changes.log`
5. Update `.on-loop/index.json` with the new session entry

### 7. Execute Agent Pipeline

Run the on-loop agent pipeline for this step. All agents operate within the worktree directory.

#### 7a. Coding Agent

Dispatch the **coding agent** (`agents/coding.md`):
- Provide the step plan from the session's `plan.md`
- Provide context about the broader feature from the roadmap
- The coding agent implements the step in the worktree

**Update heartbeat** after coding completes.

#### 7b. Testing Agent

Dispatch the **testing agent** (`agents/testing.md`):
- Provide coding agent's notes from the session directory
- Focus tests on the specific files created/modified in this step
- If tests fail and retry budget allows (max 2 retries for step-level), loop back to coding
- If retries are exhausted, record unresolved issues, mark the session and step failed, release the advisory lock, and stop. Proceed only after an explicit human waiver is recorded per `skills/quality-gate/SKILL.md`.

**Update heartbeat** after testing completes.

#### 7c. Security Agent

Dispatch the **security agent** (`agents/security.md`):
- Provide all prior agent notes from the session directory
- Focus security review on this step's files
- If CRITICAL findings and retry budget allows (max 1 retry for step-level), loop back to coding
- If retries are exhausted, record unresolved issues, mark the session and step failed, release the advisory lock, and stop. Proceed only after an explicit human waiver is recorded per `skills/quality-gate/SKILL.md`.

**Update heartbeat** after security completes.

#### 7d. Review Agent

Dispatch the **reviewer agent** (`agents/reviewer.md`):
- Provide all agent notes from the session directory
- If REQUEST_CHANGES and retry budget allows (max 1 retry for step-level), loop back to coding
- If retries are exhausted, record unresolved issues, mark the session and step failed, release the advisory lock, and stop. Proceed only after an explicit human waiver is recorded per `skills/quality-gate/SKILL.md`.

**Update heartbeat** after review completes.

Note: Documentation and build phases are skipped for individual steps. They are handled at the phase level when all steps complete, or via dedicated `/on-doc` and `/on-build` invocations.

### 8. Mark Step Complete

After successful pipeline execution:

1. Update the feature state file:
   - Set step status to `complete`
   - Set step `completed_at`
   - Increment phase `steps_completed`
2. Release the lock (per `skills/roadmap-lock/SKILL.md`)
3. Remove session from `_global.json`
4. Check if the phase is now complete (all steps done)
5. If phase complete, update phase status

### 9. Commit Step Work

After marking the step complete:

1. `cd` to the worktree directory
2. Read the session's `changes.log` for files modified
3. Stage all modified/created files (explicit paths from changes.log)
4. Also stage the session directory: `.on-loop/sessions/<session-name>/`
5. Commit with message: `feat(<feature-slug>): phase <N> step <M> - <step title>`
   - End with `Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>`
6. Also stage and commit the updated state file `roadmap/.state/<feature-slug>.json`

### 10. Finalize Session

After successful commit:

1. Update `.on-loop/index.json` session status to `"complete"`
2. **Do NOT remove the worktree** — leave it in place for the next `/on-continue` step, inspection, or resume. Worktrees are removed only by explicit `/on-loop:clear` (see AGENTS.md "Worktrees").

### 11. Handle Failure

If the agent pipeline fails:

1. Mark the step as `failed` in the state file
2. Release the advisory lock
3. Remove session from `_global.json`
4. Update `.on-loop/index.json` session status to `"failed"`
5. **Do NOT remove the worktree** (available for debugging or resume)
6. Report the failure with details
7. For an unexpected execution error, the step may be retried on a later `/on-continue` invocation. For TEST, SECURITY, or REVIEW retry exhaustion, keep the fail-closed state until an explicit human waiver covering the unresolved issues is recorded; a fresh invocation does not itself waive them.

### 12. Report

Display to the user:
- Which step was executed (phase N, step M, title)
- Summary of what was implemented
- Test results
- Security findings
- Files created/modified
- Whether the phase is now complete
- How many steps remain in the current phase
- Suggest running `/on-continue` again for the next step, or `/on-pause` to stop

## Concurrency Limitation and Follow-up

Worktrees isolate checked-out files, but roadmap state and `_global.json` remain shared ordinary JSON files. The documented read-after-write check cannot guarantee mutual exclusion: two processes can read the same state and overwrite each other's updates. TTL heartbeats also cannot by themselves prove ownership after a crash or delayed writer.

Use one roadmap-writing `/on-continue` session per feature at a time. Reliable multi-session concurrency is deliberately out of scope for this workflow hardening. Its authoritative follow-up requirements are:

1. an executable atomic lock/lease or compare-and-swap primitive around every shared-state mutation;
2. unique ownership tokens checked during heartbeat, transition, and release;
3. atomic durable writes plus stale-owner/crash recovery semantics; and
4. multi-process integration tests covering acquisition races, delayed writers, stale lease reclamation, and release by non-owners.

Do not claim conflict prevention until those mechanisms and tests exist.

## Step-Level Retry Budget

Within a single step execution, the retry budget is tighter than the full `/on-loop`:

| Transition | Max Retries |
|-----------|-------------|
| TEST -> CODE | 2 |
| SECURITY -> CODE | 1 |
| REVIEW -> CODE | 1 |

This keeps individual step execution bounded in time.

## Important

- Each `/on-continue` invocation handles exactly ONE step
- Each step gets its own worktree and session directory
- Session directories are editable operational records intended for git; they are not immutable or guaranteed complete
- State files in `roadmap/.state/` are the persistent record
- Always commit after a successful step
- Always release locks, even on failure
- Worktrees are retained on both success and failure; they are removed only by explicit `/on-loop:clear`
- Heartbeat is updated between each agent phase
