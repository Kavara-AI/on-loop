---
name: roadmap-lock
description: File-level locking with TTL, heartbeat, and stale lock detection for multi-session roadmap coordination
---

# Roadmap Lock Management

This skill manages file-level locking for multi-session coordination during roadmap execution. These locks are advisory JSON records, not atomic cross-process locks: they signal intent to work on a step but cannot by themselves guarantee mutual exclusion. Run one roadmap-writing session per feature at a time; see [`commands/on-continue.md`](../../commands/on-continue.md) for the concurrency limitation and its follow-up requirements.

## Lock Storage

Locks are stored in two places:

1. **Step-level locks**: In `roadmap/.state/<feature>.json` under `locks` and within step `assigned_session` fields
2. **Global coordination**: In `roadmap/.state/_global.json` for cross-feature concerns

## Lock Schema

### Step Lock (in feature state file)

```json
{
  "locks": {
    "<step-key>": {
      "session_id": "<uuid-v4>",
      "session_label": "<human-readable label, e.g. 'Alice laptop'>",
      "phase": 1,
      "step": 3,
      "files": ["path/to/file.py", "path/to/other.py"],
      "acquired_at": "<ISO 8601>",
      "last_heartbeat": "<ISO 8601>",
      "ttl_minutes": 60
    }
  }
}
```

### Global Lock File

`roadmap/.state/_global.json`:

```json
{
  "version": "1.0",
  "migration_lock": null,
  "active_sessions": {
    "<session-id>": {
      "session_label": "<human-readable label>",
      "feature": "<feature-slug>",
      "phase": 1,
      "step": 3,
      "started_at": "<ISO 8601>",
      "last_heartbeat": "<ISO 8601>",
      "pid": "<process identifier if available>"
    }
  }
}
```

## Operations

### Generate Session ID

When a new session starts (any command invocation that needs coordination):

1. Generate a UUID v4 using `python3 -c "import uuid; print(str(uuid.uuid4()))"`
2. Store it for the duration of the session
3. Optionally accept a `session_label` from the user for human readability

### Acquire Lock

When `/on-continue` picks up a step:

1. Read the feature state file
2. Read the global lock file
3. **Check for conflicts**:
   a. If the step has `exclusive: true`, verify no other steps in the phase are `in-progress`
   b. If the step has `conflicts_with` IDs, verify none of those steps are `in-progress`
   c. If any target files overlap with files locked by another session, the lock cannot be acquired
4. **Check for stale locks** on the target step:
   a. If a lock exists, check `last_heartbeat`
   b. If `last_heartbeat` is more than 10 minutes old, the lock is stale and can be reclaimed
   c. Log a warning when reclaiming a stale lock
5. **Write the lock**:
   a. Add entry to `locks` in the feature state file
   b. Add entry to `active_sessions` in the global lock file
   c. Set `last_heartbeat` to current timestamp
6. **Verify lock** (read-after-write):
   a. Re-read the state file
   b. Verify the lock belongs to this session
   c. If another session overwrote the lock (race condition), back off and retry once
   d. If retry fails, report that the step is unavailable

### Release Lock

When a step completes, fails, or `/on-pause` is invoked:

1. Read the feature state file
2. Verify the lock belongs to the current session (by `session_id`)
3. Remove the entry from `locks`
4. Remove the entry from `active_sessions` in the global lock file
5. Write both files

### Heartbeat

While a session is actively working on a step:

1. Every 5 minutes, update `last_heartbeat` in both:
   - The lock entry in the feature state file
   - The session entry in the global lock file
2. Use current ISO 8601 timestamp
3. The heartbeat should be written at natural checkpoints (e.g., between agent phases)

Implementation note: Since Claude Code sessions are not long-running daemons, the heartbeat is written at key milestones during step execution rather than on a timer. Each agent dispatch within `/on-continue` should update the heartbeat.

### Detect Stale Locks

When checking lock availability:

1. Read the lock entry
2. Parse `last_heartbeat` as ISO 8601
3. Compare to current time
4. If the difference exceeds 10 minutes, the lock is stale
5. Stale detection formula: `now - last_heartbeat > 10 minutes`

Use this Python snippet for comparison:
```python
python3 -c "
from datetime import datetime, timezone, timedelta
last = datetime.fromisoformat('<heartbeat_value>')
now = datetime.now(timezone.utc)
stale = (now - last) > timedelta(minutes=10)
print('stale' if stale else 'active')
"
```

### Reclaim Stale Lock

When a stale lock is detected and a session wants to acquire the step:

1. Log a warning: `[timestamp] WARNING: Reclaiming stale lock on phase <N> step <M> from session <old-session-id> (last heartbeat: <timestamp>)`
2. Remove the old lock entry
3. Remove the old session from `active_sessions`
4. Proceed with normal lock acquisition
5. Note the reclamation in the step's state for auditability

### Release All Locks (for /on-pause)

When `/on-pause` is invoked:

1. Read the feature state file
2. Find all locks belonging to the current session (by `session_id`)
3. For each lock:
   a. If the step is `in-progress`, leave it as `in-progress` (another session can reclaim via stale detection, or the same session can resume)
   b. Remove the lock entry
4. Remove the session from `active_sessions` in the global lock file
5. Write both files

## Conflict Detection

### File-Level Conflicts

Two steps conflict at the file level if their `files` arrays have any intersection:

```
Step A files: ["src/api.py", "src/models.py"]
Step B files: ["src/models.py", "src/utils.py"]
Conflict: "src/models.py" is in both -> cannot run concurrently
```

### Annotation-Based Conflicts

Steps can declare conflicts explicitly:

- `exclusive: true` -- This step cannot run while any other step in the same phase is in-progress
- `conflicts_with: [1, 4]` -- This step cannot run while steps 1 or 4 are in-progress
- `parallel: true` -- This step can run concurrently with other `parallel: true` steps (unless file conflicts exist)

### Conflict Resolution Priority

1. Check `exclusive` flag first (most restrictive)
2. Check `conflicts_with` list
3. Check file-level overlaps
4. If no conflicts, the step is eligible

## Error Handling

- **Lock file missing**: Create it with empty state
- **Lock file invalid JSON**: Back up the corrupt file, create fresh
- **Session ID mismatch on release**: Log warning, do not release (prevents accidental release of another session's lock)
- **Concurrent write detected**: Read-after-write check; back off and retry once

## Global Lock File Initialization

If `roadmap/.state/_global.json` does not exist, create it:

```json
{
  "version": "1.0",
  "migration_lock": null,
  "active_sessions": {}
}
```

The `migration_lock` field is reserved for future use (e.g., schema migrations that need exclusive access).
