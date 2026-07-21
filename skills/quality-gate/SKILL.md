---
name: quality-gate
description: Defines pass/fail criteria for phase transitions in the on-loop pipeline
---

# Quality Gate

This skill defines the quality criteria that must be met before transitioning between phases.

All paths below use `<session-dir>` to refer to the active session directory (e.g., `.on-loop/sessions/20260426_143052_user-management-api/`).

## Gate: SPEC → PLAN

**Check**: Architect agent notes exist and contain a valid specification.

| Criteria | Required |
|----------|----------|
| `<session-dir>/agent-notes/architect.md` exists | Yes |
| Specification has functional requirements | Yes |
| Specification has non-functional requirements | Yes |
| Security considerations documented | Yes |
| Architecture diagram present | Recommended |

**On fail**: Cannot proceed. Report to user.

## Gate: PLAN → CODE

**Check**: Plan is written and actionable.

| Criteria | Required |
|----------|----------|
| `<session-dir>/plan.md` has content | Yes |
| Tasks are listed with assignments | Yes |
| Constraints documented | Yes |

**On fail**: Orchestrator rewrites plan.

## Gate: CODE → TEST

**Check**: Coding agent completed implementation.

| Criteria | Required |
|----------|----------|
| `<session-dir>/agent-notes/coding.md` exists | Yes |
| Files created/modified listed in `changes.log` | Yes |
| No CRITICAL issues self-reported | Yes |
| Code compiles/parses without errors | Yes |

**On fail**: Cannot proceed. Coding agent must resolve.

## Gate: TEST → SECURITY

**Check**: All tests pass.

| Criteria | Required |
|----------|----------|
| `<session-dir>/agent-notes/testing.md` exists | Yes |
| All tests pass (zero failures) | Yes |
| Happy path tests exist | Yes |
| Error path tests exist | Yes |

**On fail (retries remain)**: Transition back to CODE with test feedback.
**On fail (retries exhausted)**: Record unresolved issues, set the session to `FAILED`, and stop. Proceed to SECURITY only after an explicit human waiver is recorded as described below.

## Gate: SECURITY → DOC/BUILD

**Check**: No critical security vulnerabilities.

| Criteria | Required |
|----------|----------|
| `<session-dir>/agent-notes/security.md` exists | Yes |
| No CRITICAL findings | Yes |
| No unmitigated HIGH findings | Yes |
| OWASP Top 10 review completed | Yes |

**On fail (retries remain)**: Transition back to CODE with security findings.
**On fail (retries exhausted)**: Record unresolved issues, set the session to `FAILED`, and stop. Proceed to DOC/BUILD only after an explicit human waiver is recorded as described below.

## Gate: DOC + BUILD → REVIEW

**Check**: Both documentation and build agents completed.

| Criteria | Required |
|----------|----------|
| `<session-dir>/agent-notes/documentation.md` exists | Yes |
| `<session-dir>/agent-notes/build.md` exists | Yes |
| README exists or was updated | Recommended |
| CI configuration exists | Recommended |

**On fail**: Warn but proceed to REVIEW (doc/build issues are non-blocking).

## Gate: REVIEW → GIT

**Check**: Reviewer approved the code.

| Criteria | Required |
|----------|----------|
| `<session-dir>/agent-notes/reviewer.md` exists | Yes |
| Verdict is `APPROVE` | Yes |
| No CRITICAL issues | Yes |

**On fail (retries remain)**: Transition back to CODE with review feedback.
**On fail (retries exhausted)**: Record unresolved issues, set the session to `FAILED`, and stop. Proceed to GIT only after an explicit human waiver is recorded as described below.

## Gate: GIT → COMPLETE

**Check**: Git operations completed successfully.

| Criteria | Required |
|----------|----------|
| All changed files staged and committed | Yes |
| Branch pushed to origin | Yes |
| PR created via `gh pr create` | Yes |
| `pr_url` set in `state.json` | Yes |

**On fail**: Report git error to user. The user can retry with `/on-loop-resume --from=GIT`.

## Retry Budget Summary

| Transition | Max Retries | Trigger |
|-----------|-------------|---------|
| TEST → CODE | 3 | Test failures |
| SECURITY → CODE | 2 | CRITICAL/HIGH findings |
| REVIEW → CODE | 2 | REQUEST_CHANGES verdict |

Total maximum code iterations: 1 (initial) + 3 + 2 + 2 = **8**

## Exhausted Retry Behavior

When TEST, SECURITY, or REVIEW retries are exhausted:
1. Record every unresolved issue in `todos` in `state.json`.
2. Set `phase` to `FAILED` and `error` to `retry_exhausted:<TEST|SECURITY|REVIEW>`.
3. Append `[timestamp] orchestrator STOP retry_exhausted:<phase> — <details>` to `changes.log`.
4. Stop and show the human the unresolved issues. Silence, a generic resume request, or a pre-existing TODO is not a waiver.
5. Continue only after the human explicitly identifies the issues they accept and directs the workflow to proceed. Append this object to `state.json.waivers`:
   ```json
   {
     "phase": "<TEST|SECURITY|REVIEW>",
     "issues": ["<accepted unresolved issue>"],
     "waiver_text": "<exact human statement>",
     "recorded_at": "<ISO 8601>"
   }
   ```
6. Append `[timestamp] orchestrator HUMAN_WAIVER <phase> — <exact human statement>` to `changes.log`, clear the retry-exhaustion error, and transition to the phase that normally follows the waived gate.

A waiver applies only to the listed phase and issues. Include all waivers prominently in the PR body and COMPLETE summary. Never infer or manufacture a waiver.
