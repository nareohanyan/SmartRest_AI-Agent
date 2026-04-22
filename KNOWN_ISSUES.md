# Known Issues And Open Risks

Last updated: 2026-04-22

This file is not a bug backlog dump. It is a curated list of the highest-signal issues a
new owner should understand early.

## 1. Scope And Trust Boundary Still Need Hardening

Why it matters:

The service is intended to be bounded by auth, subscription, and scope. That boundary is
one of the most important production safety properties of the project.

Current concern:

- effective restrictions still depend too much on request metadata and runtime resolution
- some allowlist behavior can become broader than intended if metadata is incomplete or
  not server-controlled

Relevant files:

- [app/core/auth.py](app/core/auth.py)
- [app/api/schemas.py](app/api/schemas.py)
- [app/services/agent_runtime.py](app/services/agent_runtime.py)
- [app/agent/report_tools.py](app/agent/report_tools.py)
- [app/schemas/tools.py](app/schemas/tools.py)

Recommended direction:

- move effective allowlists to trusted persisted scope/subscription state, or
- sign and validate a server-issued scope envelope instead of relying on loose metadata

Priority:

- high

## 2. Async API Boundary, Mostly Sync Runtime

Why it matters:

The FastAPI surface is async, but major downstream work is synchronous. Under load, that can
hurt latency and throughput.

Current concern:

- runtime paths still use sync graph execution and sync persistence
- the OpenAI client path is synchronous

Relevant files:

- [app/api/routes/agent.py](app/api/routes/agent.py)
- [app/services/agent_runtime.py](app/services/agent_runtime.py)
- [app/agent/llm/client.py](app/agent/llm/client.py)

Recommended direction:

- either make the service explicitly sync/threadpool-oriented, or
- migrate heavy downstream operations to async-safe implementations

Priority:

- medium

## 3. Language And Content Behavior Are Too Code-Bound

Why it matters:

The repository uses deterministic business logic and that is appropriate. But a large share
of localization, phrasing, parser synonyms, and answer style still lives directly in Python.

Current concern:

- Armenian and multilingual behavior requires code edits for too many product/content changes
- parser vocabulary and response text risk drifting from real user language

Relevant files:

- [app/agent/parser_concepts.py](app/agent/parser_concepts.py)
- [app/agent/planner_lexicon.json](app/agent/planner_lexicon.json)
- [app/agent/response_text.py](app/agent/response_text.py)
- [app/agent/llm/response.py](app/agent/llm/response.py)

Recommended direction:

- keep execution logic in code
- gradually move labels, synonyms, phrasing templates, and fallback text to config-driven data

Priority:

- medium

## 4. Ambiguous Armenian Business Terms Still Need Product Rules

Why it matters:

Users do not always ask for `revenue`, `profit`, or `margin` explicitly. Colloquial Armenian
phrasing can be ambiguous.

Current concern:

- phrases such as `փող է բերում` may mean revenue to one user and profit to another
- current behavior is practical, but product semantics are not fully codified

Recommended direction:

- define explicit product rules for ambiguous financial language
- document when the system should assume revenue and when it should ask a clarification

Priority:

- medium

## 5. Low-End Ranking Results Can Be Polluted By Technical/Test Items

Why it matters:

Queries such as "lowest revenue product" can produce technically correct but operationally
useless answers if test or technical items are included.

Current concern:

- items like `smart_print`, `test`, and similar low-signal records may appear in bottom-rank
  results depending on the tenant data

Recommended direction:

- define a product policy for excluding deleted, technical, or test items
- decide whether this should be explicit, automatic, or tenant-configurable

Priority:

- medium

## 6. Packaging And Runtime Dependency Drift Should Be Watched

Why it matters:

The project depends on both PostgreSQL-backed internal storage and a MariaDB/MySQL source-side
database for sync work. Dependency drift is easy to miss in this setup.

Current concern:

- source-side driver requirements and runtime assumptions need to remain aligned with setup docs

Relevant files:

- [pyproject.toml](pyproject.toml)
- [requirements.txt](requirements.txt)
- [.env.example](.env.example)
- [docker-compose.yml](docker-compose.yml)

Priority:

- low to medium

## 7. Full `mypy app tests` Is Not Yet A Clean Contract

Why it matters:

Application typing is in good shape, but test typing is not yet a reliable quality gate.

Current concern:

- `mypy app` passes
- full `mypy app tests` still reports a backlog of unrelated test typing issues

Recommended direction:

- keep `mypy app` as the enforced gate
- clean test typing incrementally rather than blocking product work on it

Priority:

- low

## 8. Missing Architecture Decision Records

Why it matters:

Several important choices are visible in code, but not captured as written decisions.

Examples:

- why the planner is hybrid rather than fully deterministic or fully LLM-driven
- why the project is intentionally bounded and not free-form NL-to-SQL
- why language handling is partly deterministic

Recommended direction:

- add lightweight decision records when major architectural choices are made or reversed

Priority:

- low
