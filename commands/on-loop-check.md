---
name: on-loop-check
description: Check GitHub CI status for a PR, fix regressions, alert on pre-existing failures
user_invocable: true
argument: "[PR number or branch name]"
---

# /on-loop-check

Check GitHub CI status for a PR, classify failures as regressions vs pre-existing, auto-fix regressions, and bump plugin version on success.

## Usage

```
/on-loop-check                          # Auto-detect from current branch
/on-loop-check 42                       # PR number
/on-loop-check on-loop/my-feature       # Branch name
```

## Instructions

### Step 1: Prerequisites

1. Verify `gh` CLI is authenticated:
   ```bash
   gh auth status
   ```
   If this fails, STOP and report:
   ```
   ERROR: GitHub CLI is not authenticated.
   Run `gh auth login` to authenticate, then retry /on-loop-check.
   ```
   Do not proceed with any further steps.

### Step 2: Resolve the PR

1. Read the user's argument (if any).

2. **If the argument is a number** (matches `^[0-9]+$`):
   ```bash
   gh pr view <number> --json number,title,headRefName,mergeable,state,url
   ```

3. **If the argument is a branch name** (non-numeric string):
   - Validate the branch name matches `^[a-zA-Z0-9._/-]+$`. If it does not match, STOP and report:
     ```
     ERROR: Invalid branch name. Branch names must contain only alphanumeric characters, dots, underscores, hyphens, and forward slashes.
     ```
   - Look up the PR:
     ```bash
     gh pr list --head <branch> --json number,title,headRefName,mergeable,state,url --limit 1
     ```

4. **If no argument is provided**:
   ```bash
   BRANCH=$(git branch --show-current)
   gh pr list --head "$BRANCH" --json number,title,headRefName,mergeable,state,url --limit 1
   ```

5. If no PR is found, STOP and report:
   ```
   ERROR: No open PR found for this branch.
   Create a PR first with `gh pr create` or provide the correct PR number.
   ```

6. Store the PR number, title, branch name, mergeable status, and URL for use in subsequent steps.

### Step 3: Check CI Status

1. Run the CI checks:
   ```bash
   gh pr checks <pr-number>
   ```

2. Parse the output to determine the status of each check (pass, fail, pending).

3. **If any checks are pending**, enter a polling loop to wait for completion:

   a. Report initial status:
      ```
      On-Loop Check
      =============
      PR:      #<number> -- <title>
      Branch:  <branch>
      Status:  PENDING -- CI checks still running

      Waiting for CI checks to complete...
      ```

   b. Start polling loop (max 20 cycles = 10 minutes):
      ```
      POLL_COUNT=0
      MAX_POLLS=20
      ```

   c. Every 30 seconds, re-run `gh pr checks <pr-number>` and parse the output:
      - Count total checks, passed checks, failed checks, and pending checks
      - Report progress each cycle:
        ```
        Waiting for CI... (<passed>/<total> checks complete, elapsed: <seconds>s)
        ```
      - If any check has **failed**, exit the polling loop immediately and proceed to **Step 4: Classify Failures** (no need to wait for remaining checks)
      - If ALL checks have **passed**, exit the polling loop and proceed to **Step 6: Success Path**
      - If checks are still pending and `POLL_COUNT < MAX_POLLS`, wait 30 seconds and poll again

   d. If the polling loop reaches 20 cycles (10 minutes) with checks still pending, STOP and report:
      ```
      On-Loop Check
      =============
      PR:      #<number> -- <title>
      Branch:  <branch>
      Status:  TIMEOUT -- CI checks did not complete within 10 minutes

      Completed checks:
        [PASS] <check-name>

      Still pending:
        [PENDING] <check-name>
        [PENDING] <check-name>

      The following checks are still running after 10 minutes.
      Investigate whether CI is stalled or if these checks have unusually long runtimes.
      Re-run /on-loop-check when checks complete.
      ```
      Do not proceed to classification or fixing on timeout.

4. **If ALL checks pass** (either immediately or after polling), go to **Step 6: Success Path**.

5. **If any checks fail**, proceed to **Step 4: Classify Failures**.

### Step 4: Classify Failures

For each failed check:

1. Get the workflow name from the failed check output.

2. Check the same workflow on main:
   ```bash
   gh run list --branch main --workflow "<workflow-name>" --status completed --limit 1 --json databaseId,conclusion
   ```

3. Apply classification rules:
   - If the workflow **passes** on the latest main run: classify as **REGRESSION**
   - If the workflow **fails** on the latest main run: classify as **PRE-EXISTING**
   - If the workflow **has no completed runs** on main: classify as **REGRESSION** (cannot prove pre-existing)
   - If the workflow **does not exist** on main: classify as **REGRESSION** (the PR introduced it)

4. After classifying all failures, determine the overall situation:
   - **All regressions**: go to Step 5a
   - **All pre-existing**: go to Step 5b
   - **Mixed (both regressions and pre-existing)**: go to Step 5c

### Step 5a: Fix Regressions

1. Report the regressions found:
   ```
   On-Loop Check
   =============
   PR:      #<number> -- <title>
   Branch:  <branch>
   Status:  FAILED -- <count> regression(s) detected

   Checks:
     [PASS] <check-name>
     [FAIL] <check-name> -- REGRESSION -- fixing automatically...
   ```

2. Look up the on-loop session for this branch:
   - Read `.on-loop/index.json`
   - Find the session entry whose `branch` matches the PR branch name

3. **If a session exists**:
   - Read the session's `state.json` and `plan.md` from `.on-loop/sessions/<session-name>/`
   - For each regression, get the failed log:
     ```bash
     gh run view <run-id> --log-failed
     ```
   - Dispatch the **coding agent** (`agents/coding.md`) with:
     - The session directory path
     - The worktree directory path from the session's `state.json`
     - The failed test output (pass as context, do NOT persist to a file -- logs may contain leaked secrets)
     - Instructions to fix only the regression, not modify unrelated code
     - The `plan.md` and existing agent notes for context
   - After the coding agent completes, commit and push the fix from the worktree:
     ```bash
     cd <worktree-path>
     git add -A
     git commit -m "Fix CI regression: <brief description>

     Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
     git push
     ```
   - Report to the user:
     ```
     Regression fix pushed. CI will re-run automatically.
     Run /on-loop-check again after checks complete.
     ```

4. **If no session exists**:
   - Report the regression details and failed log output
   - Suggest:
     ```
     No on-loop session found for this branch.
     To fix manually, review the failed test output above.
     If this was an on-loop session, try /on-loop-resume --from=CODE.
     ```

5. Do NOT bump versions after fixing regressions (wait for CI to pass on re-run).

### Step 5b: Alert on Pre-Existing Failures

1. STOP and report:
   ```
   On-Loop Check
   =============
   PR:      #<number> -- <title>
   Branch:  <branch>
   Status:  BLOCKED -- pre-existing failure(s) on main

   Checks:
     [PASS] <check-name>
     [FAIL] <check-name> -- PRE-EXISTING (also fails on main)

   ACTION REQUIRED:
     The following checks fail on main and are NOT caused by this PR:
       - <check-name>: <link-to-failed-run>
         (main also fails: <link-to-main-failed-run>)

     Options:
       1. Fix the failing test on main first, then rebase this branch
       2. Add the failing test to a known-failures list and re-run
       3. Contact the team to investigate the main branch failure

     This command will NOT attempt to fix pre-existing failures.
   ```

2. Do NOT dispatch any coding agent. Do NOT bump versions.

### Step 5c: Mixed Failures (Regressions AND Pre-Existing)

1. Report both categories:
   ```
   On-Loop Check
   =============
   PR:      #<number> -- <title>
   Branch:  <branch>
   Status:  MIXED -- <N> regression(s), <M> pre-existing failure(s)

   Checks:
     [PASS] <check-name>
     [FAIL] <check-name> -- REGRESSION -- fixing automatically...
     [FAIL] <check-name> -- PRE-EXISTING (also fails on main)
   ```

2. Fix the regressions using the same process as Step 5a (dispatch coding agent if session exists).

3. Alert on pre-existing failures using the same format as Step 5b.

4. Do NOT bump versions (the PR is not fully passing).

### Step 6: Success Path (All Checks Pass)

1. Report success:
   ```
   On-Loop Check
   =============
   PR:      #<number> -- <title>
   Branch:  <branch>
   Status:  ALL CHECKS PASSED
   Mergeable: <Yes/No>

   Checks:
     [PASS] <check-name> -- <duration>
     [PASS] <check-name> -- <duration>
   ```

2. If the PR is not mergeable, also note the reason (merge conflicts, review required, etc.).

3. **Version Consistency Check**:
   - Read `.claude-plugin/plugin.json` and `.claude-plugin/marketplace.json`.
   - Verify their version values match. The current release metadata is `0.6.1`.
   - If they differ, report the mismatch and stop; do not invent or automatically bump a release version.
   - If they match, report the version. Version changes belong to the explicit release process and must not be a side effect of checking a PR.

## Important

- This command does NOT create its own on-loop session. It operates as a lightweight utility.
- Failed test logs from `gh run view --log-failed` may contain secrets. Do NOT persist these logs to files. Only display them in the terminal and pass relevant excerpts to the coding agent as inline context.
- The coding agent is dispatched at most once per invocation. If the fix fails, report the failure and suggest manual intervention. Do not retry automatically.
- Always validate branch name input against `^[a-zA-Z0-9._/-]+$` before using in any shell command.
- This command validates version consistency but never bumps versions; release version changes are separate explicit work.
