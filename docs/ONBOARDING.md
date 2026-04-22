# New Engineer Onboarding

Last updated: 2026-04-22

## Goal

This guide is for an engineer taking ownership of the project without prior founder context.

The objective for the first week is not to redesign the system. It is to:

- boot it
- verify it
- understand the data and control flow
- identify the most important risks

## Day 1: Bootstrap And Validation

1. Read [README.md](../README.md) fully.
2. Create `.env` from [.env.example](../.env.example).
3. Create `.venv` and install dependencies.
4. Start the local databases with Docker Compose.
5. Run both migration tracks.
6. Run:
   - `make test`
   - `make lint`
   - `make typecheck`
7. Hit `GET /health`.

Success criteria:

- local service starts
- tests pass
- lint passes
- `mypy app` passes

## Day 2: Understand One Request End To End

Trace one business request manually through the codebase.

Suggested path:

1. [app/api/app.py](../app/api/app.py)
2. [app/api/schemas.py](../app/api/schemas.py)
3. [app/services/agent_runtime.py](../app/services/agent_runtime.py)
4. [app/agent/graph.py](../app/agent/graph.py)
5. [app/agent/planning.py](../app/agent/planning.py)
6. [app/agent/tools.py](../app/agent/tools.py)
7. [app/agent/response_text.py](../app/agent/response_text.py)

Suggested questions to answer while tracing:

- where is auth validated
- where is scope resolved
- where is route selection decided
- where does the data come from
- where is the final answer text built

## Day 3: Understand Data And Persistence

Read:

- [app/db/operational.py](../app/db/operational.py)
- [app/db/analytics.py](../app/db/analytics.py)
- [app/db/source.py](../app/db/source.py)
- [app/persistence/runtime_persistence.py](../app/persistence/runtime_persistence.py)
- [app/persistence/chat_analytics_repository.py](../app/persistence/chat_analytics_repository.py)

Understand the difference between:

- operational SmartRest data
- chat analytics persistence
- source-side sync input

## Day 4: Understand Parsing And Product Boundaries

Read:

- [app/agent/parser_concepts.py](../app/agent/parser_concepts.py)
- [app/agent/planner_lexicon.json](../app/agent/planner_lexicon.json)
- [app/agent/planning_policy.py](../app/agent/planning_policy.py)
- [app/agent/live_capabilities.py](../app/agent/live_capabilities.py)

Focus on:

- what the agent can answer
- what it intentionally refuses
- how Armenian and multilingual handling is currently implemented

## Day 5: Review Known Risks And Pick Priorities

Read:

- [KNOWN_ISSUES.md](../KNOWN_ISSUES.md)
- [docs/ARCHITECTURE.md](ARCHITECTURE.md)
- [docs/OPERATIONS.md](OPERATIONS.md)

Then write an ownership plan answering:

- what should remain stable
- what should be hardened first
- what should become config rather than code
- what should not be expanded yet

## Rules Of Thumb For Working Safely

## 1. Keep The Project Bounded

This codebase intentionally prefers controlled analytics over flexible but unsafe behavior.

## 2. Separate Understanding Bugs From Data Bugs

If the answer sounds wrong, ask:

- did the parser misread the question
- did the tool fetch the wrong data
- did the response layer phrase good data badly

## 3. Do Not Make The LLM The Source Of Truth

The model may help with wording or normalization. It should not become the business metrics
engine.

## 4. Treat Scope And Access As High-Risk Areas

Any change that affects access, scope, or metadata trust should be reviewed carefully.

## 5. Prefer Narrow Product Improvements

Incremental support for real user phrasing is safer than general semantic looseness.

## Suggested First Improvements

Reasonable first tasks for a new owner:

- document current product semantics for ambiguous Armenian finance language
- reduce hardcoded content by moving labels/synonyms to structured config
- strengthen scope and trust boundary behavior
- clean up low-end ranking noise caused by technical/test items

## Things To Avoid Early

- replacing the planner wholesale
- converting the project into free-form NL-to-SQL
- broad schema rewrites
- changing multiple execution layers at once
