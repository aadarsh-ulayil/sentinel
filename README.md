# SENTINEL

A local, deterministic safety gateway between an AI agent and its tools. Built for the Meta Global AI Developer Hackathon.

**Status:** working local proof of concept; a live Baseten Muse Spark Open file-listing run has been verified. The scripted rehearsal is model-free. The live agent uses Meta Muse Spark Open through Baseten; live calls require your own credentials. The optional authoring compiler uses Muse Spark through a separately configured Meta Model API endpoint.

## Run

Requires macOS, Python 3.12+, and [uv](https://docs.astral.sh/uv/getting-started/installation/).

```sh
uv sync
cp .env.example .env
uv run python -c 'import secrets; print(secrets.token_urlsafe(32))'
```

Paste that generated value into `SENTINEL_TOKEN` in `.env`. Generate a second distinct value for `SENTINEL_AGENT_TOKEN`; the agent uses only this restricted credential. Do not overwrite an existing configured `.env`.

```sh
uv run python -m sentinel
```

Open http://127.0.0.1:8000 and log in with `SENTINEL_TOKEN`. On the prepared machine, `./run.command` also launches the app using the existing virtual environment. The supported launcher binds only to loopback, with one worker. Never use multiple Uvicorn workers: approvals and run locks are intentionally in memory.

## Rehearse the demo

Click **Run scripted rehearsal**. It creates a run and seeded folder using fake data:

1. List files and read `notes.txt` (allowed).
2. The file includes a hidden zero-width character and a hostile instruction to leak a synthetic bank number.
3. A scripted message attempts to send that number (blocked, red).
4. A ₹300 fake payment pauses (amber). Click **Deny**.
5. `rm -rf /` is blocked; a fake installer URL is blocked before fetching.
6. Click **Kill run**, then **Activity report**.

The rehearsal deliberately requests malicious actions to prove enforcement. It does not claim a real model followed the injection. A live model may correctly refuse the hostile file itself.

Terminal equivalent:

```sh
uv run python -m sentinel.demo
# Automated rehearsal only; simulates an operator denial:
uv run python -m sentinel.demo --auto-deny
```

**Reset as new run** kills the old run and creates a fresh sandbox and counters. It never erases historical reports.

## Live Meta agent

In `.env`, set `BASETEN_BASE_URL=https://inference.baseten.co/v1`. Set `BASETEN_API_KEY_ENV` to the API-key variable name from your Baseten documentation, and add a separate line with that variable's secret value. Never commit `.env`.

```sh
uv run python -m sentinel.agent --task 'List the folder, read notes.txt, and tidy redundant drafts.'
```

The originally requested model ID `meta-models/muse-spark-open-1026` returned HTTP 404 on this account. Baseten's authenticated `/models` listing and [official example](https://www.baseten.co/resources/changelog/muse-spark-open-and-nemotron-35-super-vl-available-on-baseten/) identify the available model as `meta-models/muse-spark-open`. Set `BASETEN_MODEL` to that verified identifier (as in `.env.example`); the code retains the original requested ID as its fallback. The loop uses the `openai` Python SDK and Chat Completions, up to 15 steps. It parses a fixed JSON action shape, validates requests at the gateway, and polls paused actions until they resolve. It has no direct real tool implementations.

## Architecture and files

```text
Meta agent (separate process)
       | HTTP action + bearer token
       v
FastAPI gateway --> pure Python policy --> allow / block / pause
       |                       | pause: operator or 60-second timeout
       v                       v
bounded tool execution <--- approval
       |
SQLite WAL audit + per-run counters --> SSE dashboard + report
```

- `sentinel/models.py`: Pydantic action, verdict, and closed-set rule contracts.
- `sentinel/policy.py`: reads actions, counters, and human rules; returns the most restrictive verdict. No network or model calls.
- `sentinel/tools.py`: real file, bounded command, text fetch, simulated message, and simulated payment implementations.
- `sentinel/storage.py`: SQLite schema, persisted decisions, successful-execution counters.
- `sentinel/app.py`: authenticated routes, per-run serialization, approval events, SSE, kill/reset, and report endpoints.
- `sentinel/templates/`: Jinja2 dashboard and report. Vanilla JavaScript handles SSE and controls; HTMX refreshes reports; Tailwind CDN is available, with core styling local in the template.
- `sentinel/agent.py`: live Meta loop, HTTP stubs only.
- `sentinel/demo.py`: deterministic demo rehearsal, explicitly separate from the live model.
- `sentinel/compiler.py`: optional model-assisted rule drafting and deterministic test gate.
- `tests/`: policy tables and gateway integration tests.
- `.runtime/`: ignored local database, per-run sandboxes, quarantine, and outbox.
- `.env`: ignored credentials; `.env.example` is the safe public configuration template.
- `uv.lock`: committed dependency versions for reproducibility.

## Rules

All nine rule types are implemented. Block beats pause; pause beats allow. Engine exceptions block. Only successful executions update counters. Payment values are positive integer rupees (no floats or booleans).

Defaults: sandbox-only file access, at most three deletions, ₹500 cumulative spend, human approval above ₹250, bank-number and OTP pattern blocking, recipients `alice`/`bob`, a three-command terminal allowlist, `example.com` domain allowlist, and a 1 MB text-only download cap with executable/archive blocking.

Run serialization prevents two simultaneous actions from both spending the same remaining budget. Runs pin their rules version. Human approval never overrides a blocking verdict. Each decision records who decided, rule ID, reason, timestamp, and rule version.

Downloads resolve DNS, reject non-public destinations, pin a public IP for the actual TLS connection, retain hostname certificate validation, refuse redirects and compressed responses, enforce a streaming byte cap, and save UTF-8 text to quarantine outside the sandbox. Downloads are never executed. Terminal execution uses no shell and permits only `pwd`, `ls`, and `whoami` with no arguments. Regex alone cannot safely contain arbitrary shell commands.

## Optional rule compiler

Configure `META_BASE_URL`, `META_MODEL`, and `META_API_KEY_ENV` plus its corresponding secret, using your Meta documentation. In the dashboard, enter a rule and choose **Draft and test**.

One model call produces a single structured rule; Pydantic rejects extra fields and unknown types. A second proposes three allow and three block examples. The deterministic engine evaluates them; a fixed template provides the English readback. Only a passing draft can be explicitly activated. New rules append to the base rules and apply only to new runs; they cannot remove protections.

The compiler's required test gate is literal: three allow and three block examples. Pause-only rule drafts may fail this gate and remain unactivatable. Model-proposed tests are examples, not a proof of correctness. No generated code is executed. Compiler prompts and drafts are stored in the local compile log. Live API behavior must be verified with account credentials.

## Verification

Verified locally: 60 automated tests, a live Muse Spark Open listing run using the restricted agent token, and browser login, scripted rehearsal, human denial, kill, and activity report. Compiler calls are mocked in tests; live Meta compiler verification still requires its separate API key.

## Tests

```sh
uv run pytest -q
```

Tests include traversal, symlinks, payment splitting and concurrency, spaced and Unicode OTPs, dangerous commands, encoded download extensions, malformed arguments, authentication/origin restrictions, human approval and denial, timeout, kill/reset, preserved reports, and the action cap.

## Limits and threat model

- SENTINEL governs only actions that go through its gateway. An agent that bypasses it, including one driving the screen or mouse directly, is outside its control.
- This is a proof of concept, not an OS sandbox or production security boundary. Agent/gateway processes run as the same user. Do not give an untrusted process unrestricted local access and expect this Python gateway to contain it.
- Humans choose the rules. Model-authored drafts require review. Runtime policy checks never call a model.
- The agent and operator use separate tokens. Agent credentials cannot approve/deny, kill/reset, or compile/activate rules. These are local bearer tokens, not a multi-user identity system. A same-user process that reads the operator's `.env` can still bypass this distinction.
- Path checks use `resolve()` and `is_relative_to()`. They reject traversal and existing escape symlinks, but do not prevent a hostile external same-user process racing filesystem changes. Do not modify sandbox symlinks concurrently.
- Kill prevents later execution and resolves pending approvals. It cannot undo or guarantee cancellation of an already executing external operation. Execution and SQLite commits are not an atomic transaction; a crash between them can leave an interrupted record after a side effect. Such actions are never automatically retried.
- Restart marks unfinished runs/actions interrupted. Approvals are not resumed. One server process only.
- The fixed message detectors are heuristic patterns, not complete data-loss prevention. Downloads permit only a conservative text subset, not arbitrary web browsing or malware scanning.
- Audit records can contain requested message contents and file data. Keep the demo synthetic. Local runtime data and secrets are Git-ignored; audit logs are not tamper-proof against the local account.
- Dashboard CDN assets require internet; core dashboard styling and controls are local, but HTMX report refresh needs its CDN asset.
- This project contains new application code created for this event; third-party dependencies retain their own licenses. Hackathon eligibility and model access remain subject to the organizer's rules.

## Git basics

`git status` shows changes. `git diff` shows edits. `git add <file>` stages a file. `git commit -m "message"` records a local snapshot. `git push` publishes committed changes to the configured GitHub remote. Always inspect `git diff --cached` before publishing. Never force-add `.env` or `.runtime/`.
