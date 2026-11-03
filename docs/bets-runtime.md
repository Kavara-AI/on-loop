# Local bet lifecycle prototype

This is the first executable slice of a bet-oriented operating model. A bet has a
question, hypothesis, wrong-question check, at least two candidate names, evidence
specification, kill criteria, allocation budget and fixed start/end. The worker
does the work; a separately configured oracle evaluates its artifacts. There is
no built-in model/provider and no cloud deployment.

Python 3.9+ on Linux/macOS; standard library only. From the repository root:

```bash
python3 -m unittest discover -s tests -p test_bets.py -v
python3 -m examples.bets.demo /tmp/bets-book.html
```

The demo executes two local sorting candidates, writes an artifact, verifies that
artifact against the worker receipt with an independent oracle, records the
decision and verifies replay. It makes no model/API calls. Open the generated HTML
book in a browser. It is a disposable demonstration, not research efficacy.

## A real bet

Create a JSON spec with these fields (timestamps are explicit and must be changed
for a new bet; the runtime never restarts a deadline):

```json
{
  "question": "Does candidate B reduce held-out error relative to A?",
  "hypothesis": "B improves the preregistered metric",
  "wrong_question_check": "Perhaps the relevant constraint is latency, not error",
  "candidates": ["A", "B"],
  "evidence_spec": "Both candidates on the same held-out samples; independent oracle",
  "kill_criteria": "No practical lift, invalid evidence, or deadline",
  "starts_at": "2026-11-03T14:00:00-05:00",
  "ends_at": "2026-11-05T14:00:00-05:00",
  "budget_microusd": 0,
  "reservation_microusd": 0
}
```

```bash
python3 -m bets.runtime --db /private/work/bets.db open /private/work/bet.json
python3 -m bets.runtime --db /private/work/bets.db recall 'held-out error'
# Substitute the returned urn:uuid identifier. Commands are explicit argv, not shell strings.
python3 -m bets.runtime --db /private/work/bets.db run urn:uuid:RETURNED-ID \
  --worker '["python3", "/private/work/approved_worker.py"]' \
  --oracle '["python3", "/private/work/independent_oracle.py"]'
python3 -m bets.runtime --db /private/work/bets.db book /private/work/book.html
python3 -m bets.runtime --db /private/work/bets.db events
```

The configured worker can invoke an existing approved coding/research agent.
It receives the pinned bet state on stdin and must evaluate all required
candidates, persist its artifacts in an agreed private workspace, and return zero
only after completion. The oracle receives state and the worker receipt on stdin;
it must verify the actual artifacts and evidence specification. Its exit code is
0=won, 10=killed, 20=inconclusive; any other code is inconclusive. A successful
worker alone never wins a bet. The runtime does not interpret free-text kill
criteria or verify scientific validity: the trusted oracle implements those rules.
Raw stdout is hashed and discarded; stderr is discarded. Do not put credentials
in argv, specs or artifacts. A worker must persist useful diagnostics privately.

## Bounds and recovery

Opening performs lexical recall and stores the matching prior bet references in
the immutable opening event, including prior kills. This is not semantic recall.
Each local dispatch transactionally reserves its declared maximum allocation
before spawning. A worker and oracle share the original deadline; local process
groups are killed on timeout/exit. SQLite write serialization prevents a second
controller dispatching the same bet. A crash leaves an active attempt and its
reservation in place: replacement execution is refused, never automatically
replayed. Manual reconciliation of abandoned attempts is not implemented here.

MicroUSD are integers (1 USD = 1,000,000 microUSD). Reservations are conservative
accounting allocations and are never refunded. They are **not actual billing or
a provider-enforced spend cap**. Only run trusted, already authorised commands
with their own provider/compute limits. These processes are not sandboxed; a
descendant deliberately escaping its process group is outside this prototype.
The adapter has no network listener, credential management, autonomous agent
discovery, portfolio allocation, multi-host execution or live service changes.

Events are append-only under the application interface and SQLite triggers;
current state and HTML book are rebuilt from ordered events. A database owner
can modify the database: this is not cryptographic attestation. Keep the DB and
book in a private directory with appropriate filesystem permissions. The HTML
escapes user text, embeds a minimal JSON-LD projection and uses a restrictive CSP.

## Relationship to the shared system

SQLite is a **disposable local test adapter**, not a replacement decision for the
planned append-only PostgreSQL source of truth. Shared ontology/Vault-LD roundtrip,
pgvector recall, MCP methods, graph projection, subscriptions, authenticated
multi-agent orchestration and actual provider-budget enforcement remain open.
This slice therefore does not complete the shared-memory or scheduler phases.

Next integration: implement the same lifecycle against the accepted PostgreSQL
event schema, bind the configured worker to an existing agent and oracle, and
exercise one real bet with its actual permitted inputs. Public examples remain
synthetic; private workstream plans/credentials must not be committed here.
