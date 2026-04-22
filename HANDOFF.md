# SmartRest AI Agent Handoff

Last updated: 2026-04-22

## Purpose

This document is the operational and engineering handoff for the next owner of the
SmartRest AI Agent repository. It is intended to reduce founder-memory risk and make
the project transferable to a new engineer without relying on informal context.

This project is not a generic chatbot. It is a bounded analytics backend that uses:

- FastAPI for the API layer
- LangGraph for orchestration
- typed Pydantic schemas as the contract boundary
- database-backed reporting and analytics as the source of truth
- OpenAI for constrained interpretation and response composition
- chat analytics persistence for runtime traceability

## Current Assessment

The repository is in a credible handoff state, but not a fully finished or fully hardened
production state.

What is already strong:

- local bootstrap instructions exist in [README.md](README.md)
- operational commands are centralized in [Makefile](Makefile)
- environment variables are documented in [.env.example](.env.example)
- migration tracks are separated for operational and chat analytics schemas
- sync flows are present and documented
- test coverage is broad across parsing, graph behavior, runtime, persistence, and DB paths
- `ruff` passes
- `mypy app` passes
- `pytest` passes in the current local environment

What is still founder-dependent:

- some architectural intent still lives more in code than in documentation
- product rules around Armenian interpretation and answer behavior are only partly documented
- trust-boundary and scope-hardening decisions are not yet fully resolved
- there is no admin UI or product-facing configuration layer for language/content behavior

Bottom line:

- safe to transfer to another engineer: yes
- safe to abandon without written context: no

## What The Next Engineer Should Understand First

The system has four major stages:

1. Request validation
   Tenant or admin request enters through FastAPI and is verified for auth and access.

2. Intent normalization and planning
   User language is interpreted into a bounded query shape. This is partly deterministic
   parser logic and partly LLM-assisted planning depending on planner mode.

3. Execution
   Tools and services retrieve grounded data from SmartRest-backed storage and analytics
   persistence. The model is not the business truth layer.

4. Answer rendering
   Structured results are turned into localized user-facing text, with optional LLM
   rewriting for fluency.

That split matters. If a bug appears, first decide which layer owns it:

- parser/planning bug
- data retrieval bug
- authorization/scope bug
- response wording bug

## Recommended Reading Order

For a new engineer, the fastest route to understanding is:

1. [README.md](README.md)
2. [docs/ONBOARDING.md](docs/ONBOARDING.md)
3. [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
4. [docs/OPERATIONS.md](docs/OPERATIONS.md)
5. [KNOWN_ISSUES.md](KNOWN_ISSUES.md)

Then read code in this order:

1. [app/main.py](app/main.py)
2. [app/api/app.py](app/api/app.py)
3. [app/api/schemas.py](app/api/schemas.py)
4. [app/services/agent_runtime.py](app/services/agent_runtime.py)
5. [app/agent/graph.py](app/agent/graph.py)
6. [app/agent/planning.py](app/agent/planning.py)
7. [app/agent/response_text.py](app/agent/response_text.py)
8. [app/agent/services/live_business_tools.py](app/agent/services/live_business_tools.py)
9. [app/persistence/runtime_persistence.py](app/persistence/runtime_persistence.py)
10. [tests/test_graph.py](tests/test_graph.py)

## Current Product Boundaries

The agent is intended for bounded business analytics questions. It is not intended for:

- free-form open-domain chat
- unrestricted NL-to-SQL
- policy/legal/medical advice
- broad operational control of SmartRest

Current strengths:

- report-like KPI questions
- comparisons
- rankings
- trends
- selected business breakdowns
- bounded Armenian business phrasing for supported analytics intents

Current limitations:

- not every colloquial Armenian phrasing is covered
- live analytics coverage is selective, not universal
- exclusion grammar was recently expanded for item queries, but not every filter type
- some language and response behavior is still code-heavy rather than configuration-driven

## Recent Important Changes

The following areas were recently improved and should be known by the next engineer:

1. Armenian answer naturalness
   User-facing Armenian response text was improved to reduce generic, mechanical wording.

2. Colloquial Armenian item-revenue phrasing
   Item queries now better handle phrasing such as asking which product "brings the least money".

3. Item exclusion support
   Queries like "except smart_print" / `բացի smart_print ապրանքից` now have explicit support
   in the item-performance path.

4. Lint/type hygiene
   `ruff` and `mypy app` currently pass in the local checked state.

## Non-Goals For A New Engineer's First Week

Do not start by rewriting the planner or replacing the orchestration stack.

Avoid these until the current behavior is understood:

- replacing LangGraph
- turning the project into free-form NL-to-SQL
- moving all parser behavior to LLM-only logic
- broad schema rewrites
- removing deterministic guardrails around analytics tools

## Recommended First-Week Tasks For A Successor

1. Bootstrap the project locally from [README.md](README.md).
2. Run `make test`, `make lint`, and `make typecheck`.
3. Read [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).
4. Trace one request from API input to final answer.
5. Review [KNOWN_ISSUES.md](KNOWN_ISSUES.md) and decide the first ownership priorities.
6. Confirm the local DB/sync assumptions with real test data.

## Handoff Risk Summary

The main handoff risk is not code quality. It is context quality.

The biggest lost-context areas are:

- why some planner behavior is deterministic and intentionally narrow
- what should remain hardcoded versus become configuration
- how scope enforcement is intended to evolve
- what product meaning should be assigned to ambiguous Armenian business wording

Those topics are documented at a high level in the files added with this handoff package,
but they still require product/engineering judgment from the next owner.

## Minimum Handoff Checklist

Before this project is considered fully handed over, the next owner should confirm:

- they can boot the service locally
- they can run tests locally
- they understand the dual-database setup
- they understand deterministic parser versus LLM-assisted planning
- they understand current product boundaries
- they have reviewed known issues and open decisions

## Documentation Index

- [README.md](README.md): project overview, setup, bootstrap, commands
- [KNOWN_ISSUES.md](KNOWN_ISSUES.md): current technical and product risks
- [docs/ONBOARDING.md](docs/ONBOARDING.md): first-week guide for a new engineer
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md): request/data/control flow
- [docs/OPERATIONS.md](docs/OPERATIONS.md): environments, checks, migrations, sync, runbook
