#!/usr/bin/env bats

setup() {
  REPO_ROOT="$(cd "$BATS_TEST_DIRNAME/.." && pwd -P)"
  cd "$REPO_ROOT"
}

@test "plugin metadata uses current version and Mirepoix-AI URLs" {
  run python3 - <<'PY'
import json
from pathlib import Path
plugin = json.loads(Path('.claude-plugin/plugin.json').read_text())
market = json.loads(Path('.claude-plugin/marketplace.json').read_text())
assert plugin['version'] == '0.6.1'
assert market['plugins'][0]['version'] == plugin['version']
assert plugin['repository'] == 'https://github.com/Mirepoix-AI/on-loop'
assert plugin['homepage'] == 'https://github.com/Mirepoix-AI/on-loop#readme'
assert market['owner']['name'] == 'Mirepoix-AI'
PY
  [ "$status" -eq 0 ]

  [ "$(find commands -maxdepth 1 -type f -name '*.md' | wc -l | tr -d ' ')" = "18" ]
  grep -q 'Plugin metadata (v0.6.1)' README.md
  grep -q 'commands/.*18 user-invocable commands' README.md
}

@test "workflow is described as prompt guidance rather than executable coordination" {
  grep -q 'not an executable coordinator' README.md
  grep -q 'not a mechanically enforced executable coordinator' commands/on-loop.md
  grep -q 'workflow and bootstrap plugin' .claude-plugin/plugin.json
}

@test "retry exhaustion fails closed pending a recorded human waiver" {
  for file in \
    agents/orchestrator.md \
    commands/on-loop.md \
    commands/on-loop-continue.md \
    commands/on-continue.md \
    commands/on-loop-resume.md \
    skills/quality-gate/SKILL.md \
    skills/loop-state/SKILL.md \
    shared/COMMUNICATION_PROTOCOL.md; do
    grep -qi 'human waiver' "$file" || {
      echo "missing human-waiver contract: $file" >&2
      return 1
    }
  done

  ! grep -R -Eqi '(if retries exhausted, record TODOs? and continue|on fail \(retries exhausted\).*record TODO, proceed|if exhausted: record TODO and advance)' \
    agents commands skills shared
  grep -q '"waivers": \[\]' skills/loop-state/SKILL.md
  grep -q 'HUMAN_WAIVER' skills/quality-gate/SKILL.md
}

@test "resume permits GIT without bypassing review" {
  grep -q 'REVIEW, GIT)' commands/on-loop-resume.md
  grep -q -- '--from=GIT.*requires prior review approval or a recorded REVIEW waiver' commands/on-loop-resume.md
}

@test "cleanup never merges and successful loop worktrees are retained" {
  ! grep -q 'gh pr merge' commands/on-loop-clear.md
  grep -q 'Never merge a PR as a side effect of cleanup' commands/on-loop-clear.md
  grep -q 'Retain the worktree' agents/orchestrator.md
  grep -qi 'do not remove the worktree' commands/on-loop.md
  grep -q 'Retains worktree on complete' commands/on-loop-continue.md
}

@test "documentation does not call editable git records immutable" {
  run grep -Rni 'immutable audit\|immutable NDJSON\|logged immutably' \
    README.md CLAUDE.md agents commands skills shared bin
  [ "$status" -eq 1 ]
}

@test "roadmap concurrency claims remain bounded to current evidence" {
  grep -q 'run only one roadmap-writing `/on-continue` session per feature at a time' commands/on-continue.md
  grep -q 'executable atomic lock/lease or compare-and-swap primitive' commands/on-continue.md
}
