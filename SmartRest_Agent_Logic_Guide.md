# SmartRest Agent — Logic Guide

This file explains the **whole logic of the project**.

Whenever the project starts feeling confusing, this is the file to read.

Its purpose is to answer:

- What are we actually building?
- Why are we building it this way?
- What is an agent in this project?
- What is LangGraph doing?
- What is OpenAI doing?
- What are tools?
- Why are we delaying database integration?
- How does everything connect together?

---

# 1. What the project really is

This project is **not** a generic chatbot.

It is a **SmartRest business-reporting agent**.

That means the system should ultimately do this:

1. receive a business question from a SmartRest user
2. understand what the user wants
3. understand what data/report is needed
4. check what the user is allowed to access
5. choose the correct strategy
6. call tools to get the needed information
7. return a useful and correct answer

Examples:
- “What were Glovo sales last month?”
- “How many orders did we have yesterday?”
- “What is the average check this week?”
- “Compare delivery channels for March.”

So the project is about **intelligent reporting and analytics**, not free-form chatting.

---

# 2. What a real agent means here

A real agent is **not just an LLM call**.

A real agent in this project means a system that has:

- state
- workflow
- tool usage
- routing decisions
- persistence
- controlled outputs

In other words, a real agent must:
- reason about the request
- choose what to do next
- call tools instead of inventing data
- keep execution state
- produce a final answer based on tool outputs

So the project becomes a real agent only when these parts exist together.

---

# 3. The 3-layer mental model

The cleanest way to understand the architecture is this:

## Layer 1 — Agent runtime
This is the orchestration brain.

Includes:
- LangGraph workflow
- agent state
- routing logic
- node execution
- persistence

## Layer 2 — Tool layer
These are the actions the agent can take.

Includes:
- resolve scope
- list reports
- get report definitions
- run reports
- later: query SmartRest DB

## Layer 3 — Backend implementation
This is where data and business retrieval actually happen.

Now:
- mock/prototype backend

Later:
- real SmartRest database / semantic reporting backend

The important idea is:

**Layers 1 and 2 can be built now. Layer 3 can be replaced later.**

That is why we can build the real agent before the real DB is available.

---

# 4. Why we are not waiting for the database

Database access is a backend integration problem.

It is **not** the same thing as the agent runtime.

If we wait for DB access before building the agent, we delay:
- state design
- workflow design
- tool design
- API shape
- observability
- tests
- answer flow

That would be a mistake.

The correct approach is:

1. build the agent runtime now
2. build stable tool interfaces now
3. connect the real DB later through one backend/tool implementation

So the future DB should be a **plug-in replacement**, not the center of the whole architecture.

---

# 5. Why LangGraph is important

LangGraph is the **runtime for the agent**.

Without LangGraph, the system risks becoming:
- many disconnected service files
- route handlers that do too much
- unclear execution flow
- no real state machine

LangGraph solves that by giving the project:
- explicit state
- explicit nodes
- explicit transitions
- durable execution
- persistence/checkpointing
- ability to add interrupts later

So when we say “where is the real agent?”, LangGraph is one of the main answers.

It should be the place where the workflow lives.

---

# 6. Why OpenAI is important

OpenAI is **not** the whole agent.

It is one part of the system.

In this project, OpenAI should be used for:
- understanding the user question
- extracting structured intent and filters
- helping choose the right report path
- composing the final answer naturally

At the beginning, OpenAI should **not** be used for:
- direct raw SQL generation
- unchecked business calculations
- inventing answers without tools

So OpenAI is the **interpretation and language layer**, not the source of truth.

---

# 7. Why tools are necessary

If the model answers business questions directly, it can hallucinate.

That is dangerous for reporting.

So the model should use tools.

A tool is simply a structured action the agent can call.

Examples:
- resolve the user scope
- list the reports the system supports
- get the definition of a report
- run a report
- later: query the semantic reporting layer

The agent becomes trustworthy when:
- the model decides what it needs
- the tools fetch or compute that information
- the final answer is based on those tool results

---

# 8. What the first real version of the agent should do

The first real version should support this flow:

1. user sends a question
2. agent resolves user scope
3. agent uses OpenAI to interpret the question
4. agent determines whether the request is:
   - supported
   - unclear
   - unsupported
5. if supported, the agent calls the correct report tool
6. the agent receives the report result
7. the agent composes a final answer
8. the run is persisted

That is already a real working agent.

---

# 9. What the first graph should look like

The first LangGraph workflow should be simple.

## Node 1 — `resolve_scope`
Purpose:
- determine who the user is
- determine allowed scope
- determine allowed reports or permissions

## Node 2 — `interpret_request`
Purpose:
- use OpenAI to interpret the question
- identify intent
- identify report id
- extract filters
- decide whether clarification is needed

## Node 3 — `route_decision`
Purpose:
- choose the next step based on the interpreted request

Possible routes:
- run report
- ask clarification
- reject unsupported request

## Node 4 — `run_report`
Purpose:
- call the report tool with the chosen report id and filters

## Node 5 — `compose_answer`
Purpose:
- produce the final user-facing answer

## Optional nodes later
- approval node
- semantic query node
- explanation node
- anomaly explanation node

The first graph must stay simple.

---

# 10. What the state object is for

The state object is the shared memory of one agent run.

It prevents the system from becoming a pile of disconnected function calls.

It should carry the key facts of the run:
- what the user asked
- what scope was resolved
- how the question was interpreted
- which report was chosen
- what filters were extracted
- what tool outputs were produced
- what final answer was returned

If the state is well designed, the whole workflow becomes understandable.

---

# 11. What the API should and should not do

## The API should do
- receive the request
- validate the payload
- create ids / metadata
- call the agent service
- return the final result

## The API should not do
- business routing logic
- report selection logic
- interpretation logic
- graph orchestration logic
- deep business calculations

That logic belongs in the agent runtime and tools.

---

# 12. Why report tools come before database tools

Right now the project goal is to build a real agent runtime.

To do that, the agent needs something meaningful to call.

The safest first meaningful tools are deterministic report tools.

Why?
Because they are:
- easier to test
- easier to reason about
- safer than ad-hoc SQL
- closer to real business answers

Later, when the SmartRest DB is ready, those report tools can use the real reporting backend underneath.

So the path is:

1. report tools now
2. DB-backed implementations later

---

# 13. What the backend abstraction means

The backend abstraction is the line that separates:
- the agent runtime
from
- the data implementation

This is extremely important.

If the agent runtime depends directly on the DB structure, then every DB issue blocks the whole project.

If the agent runtime depends only on a stable tool/backend interface, then the project can progress independently.

That is why the future real DB should be just one implementation of a backend contract.

---

# 14. Why observability comes after the graph works

LangSmith is very important.

But it is only useful after the workflow actually exists.

You trace:
- model calls
- tool calls
- graph execution
- failures
- outputs

If the graph is not built yet, observability has nothing meaningful to observe.

So the right timing is:
1. get the graph running
2. then add LangSmith

---

# 15. What is intentionally delayed

The following things are intentionally delayed until the core runtime exists:

- real SmartRest DB connection
- semantic SQL
- raw NL-to-SQL
- inventory/fiscal complexity
- approval flows
- advanced memory
- long multi-turn planning
- production scaling concerns

This is not because they are unimportant.

It is because adding them too early would make the project chaotic.

---

# 16. What “done enough for now” means

The first major success state is:

- FastAPI receives a question
- LangGraph starts a run
- scope is resolved
- OpenAI interprets the request
- the graph routes correctly
- a report tool is called
- the answer is composed
- the run is persisted
- later this is visible in LangSmith

At that point, the project is no longer “a pile of code files.”

It is a real agent runtime.

---

# 17. What happens later when DB access arrives

When the SmartRest database becomes available, we do **not** rebuild the project.

We do this instead:

1. inspect the real DB
2. build a semantic/reporting backend
3. implement real report runners or DB-backed tool implementations
4. plug them into the existing tool layer
5. validate real answers
6. add observability and evaluation around them

That is the payoff of the architecture.

The runtime stays.
The backend changes.

---

# 18. The most important rules of the project

## Rule 1
Do not let the model answer business data questions without tools.

## Rule 2
Do not place orchestration logic in API routes.

## Rule 3
Do not skip explicit state.

## Rule 4
Do not skip LangGraph if the goal is a real agent.

## Rule 5
Do not use OpenAI as the source of truth for business data.

## Rule 6
Do not wait for the DB to build the runtime.

## Rule 7
Do not overbuild advanced features before the first graph works.

---

# 19. The shortest explanation possible

If everything becomes confusing, remember this:

We are building:

**a LangGraph-powered, OpenAI-interpreted, tool-using SmartRest reporting agent**

where:
- the graph controls the workflow
- the model interprets and composes
- the tools do the real work
- the backend can be replaced later

That is the whole logic.

---

# 20. If you forget everything else, remember this order

1. project skeleton
2. state
3. tools
4. report contracts
5. OpenAI interpretation
6. LangGraph workflow
7. persistence
8. API boundary
9. answer composition
10. observability
11. real DB later

That is the correct build order.
