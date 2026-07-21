# On-Loop Plugin

Mirepoix Claude Code SDLC workflow/bootstrap plugin. Its Markdown commands and agent prompts guide a lifecycle; they are not a mechanically enforced executable coordinator or complete event-log system.

## Commands

- `/on-loop <prompt>` — Guide Claude Code through the spec -> code -> test -> security -> docs -> build -> review -> git workflow
- `/on-loop-continue <prompt>` — Continue the workflow in an existing on-loop worktree (commits and pushes, no new worktree or PR)
- `/on-loop-check [PR number or branch]` — Check GitHub CI status, fix regressions, alert on pre-existing failures
- `/on-loop-debug-fix [description or image] [--complexity=level]` — Debug and fix issues from infrastructure logs or user-provided context
- `/on-loop-status` — Check current loop progress and list all sessions
- `/on-loop-resume [--from=phase] [--session=<id>]` — Resume an interrupted loop
- `/on-loop:clear [--include-logs]` — Remove worktrees and optionally session records; never merge PRs or switch branches
- `/on-loop:main-resolve` — Pull main, merge into current branch, resolve conflicts
- `/on-spec <description>` — Standalone spec generation
- `/on-test <target>` — Standalone test generation
- `/on-security <target>` — Standalone security audit
- `/on-doc <target>` — Standalone documentation generation
- `/on-build <target>` — Standalone build/CI setup
- `/on-review <target>` — Standalone code review

### Roadmap Commands (Multi-Session)

- `/on-prepare <prompt>` — Generate a roadmap with phases, steps, and acceptance criteria from a full prompt
- `/on-plan [feature-slug]` — Read roadmap, produce detailed implementation plan with parallelism annotations
- `/on-continue [feature-slug]` — Pick up next available step and execute through agent pipeline
- `/on-pause [feature-slug]` — Release locks, commit WIP, write handoff summary

## Architecture

Each `/on-loop` session is directed to operate in a **git worktree** at `.claude/worktrees/<branch-slug>/`. Worktrees isolate checked-out feature files; shared session metadata remains prompt-managed.

### Session Logs

Session state is persisted under `.on-loop/sessions/<YYYYMMDD_HHMMSS_branch-slug>/`:
- `state.json` — Phase tracking (only orchestrator writes)
- `plan.md` — Implementation plan (all agents read)
- `changes.log` — Workflow-appended file modification record
- `agent-notes/<agent>.md` — Structured output per agent

The session index at `.on-loop/index.json` tracks all sessions.

Session directories are intended to be committed as editable operational records; they are not immutable or guaranteed complete.

### Worktrees

Worktrees at `.claude/worktrees/` are gitignored and temporary:
- Created during INIT
- Used for all agent work (SPEC through REVIEW)
- Commits and pushes happen from the worktree (GIT phase)
- Retained on COMPLETE for `/on-loop-continue` or inspection, and on FAILED for resume
- Removed only by explicit `/on-loop:clear`, which never merges PRs

## Agent Roster

| Agent | Role |
|-------|------|
| orchestrator | Pipeline control, quality gates, retry logic, worktree/session lifecycle |
| architect | Spec generation, ADRs, system design |
| coding | Implementation with security-first practices |
| testing | Unit, integration, and E2E tests |
| security | OWASP/STRIDE audit, compliance checks |
| documentation | READMEs, guides, CLAUDE.md files |
| build | Makefile, CI/CD, lint/security configs |
| reviewer | Final code review gate |

## Quality Standards

Agent prompts adopt a Staff Engineer and ISC2-informed security posture targeting regulated environments. This is a requested review perspective, not a claim that a model holds professional credentials. See `shared/AGENT_PERSONA.md` and `shared/QUALITY_STANDARDS.md`.

## Workspace Convention

- `.on-loop/` — Editable session records intended to be committed to the repo
- `.on-loop/index.json` — Session manifest
- `.on-loop/sessions/<YYYYMMDD_HHMMSS_slug>/` — Per-session state, plan, changes, agent notes
- `.claude/worktrees/` — Temporary git worktrees (gitignored)

## Roadmap Convention

The `roadmap/` directory is persistent and committed to the repo. It contains:
- `roadmap/<feature>.md` — Roadmap documents with phases, steps, mermaid diagrams
- `roadmap/.state/<feature>.json` — State tracking per feature (phase/step status, locks)
- `roadmap/.state/_global.json` — Cross-session coordination (active sessions, global locks)

Each `/on-continue` session gets its own worktree and session directory. Current roadmap locks are prompt-managed JSON records, not atomic cross-process locks; use one roadmap-writing session at a time. Safe concurrency remains follow-up work requiring an executable atomic lock/lease or compare-and-swap mechanism, owner-verified release, crash recovery, and multi-process integration tests. See `commands/on-continue.md`.

## Skills

| Skill | Purpose |
|-------|---------|
| `skills/roadmap-state/` | State file operations: init, read, transition, step tracking |
| `skills/roadmap-lock/` | Lock acquisition, release, heartbeat, stale detection |
| `skills/quality-gate/` | Pass/fail criteria for phase transitions |
| `skills/loop-state/` | On-loop phase state transitions and validation |

## Maintaining this file

Keep this file for knowledge useful to almost every future agent session in this project.
Do not repeat what the codebase already shows; point to the authoritative file or command instead.
Prefer rewriting or pruning existing entries over appending new ones.
When updating this file, preserve this bar for all agents and keep entries concise.
