You are a senior AI systems architect and backend engineer.

I want you to create a detailed improvement implementation plan for my current SmartRest AI agent project.

The goal is not to redesign everything from scratch. The goal is to evolve the current project into a more capable, well-structured, dynamic analytics agent while preserving what is already good and stable.

You must write the plan as if you are advising a serious production-minded engineering team.

Context about the current project state
- The project already has a clean backend structure with clear app layering.
- It already includes:
  - FastAPI boundary
  - LangGraph workflow
  - typed schemas/contracts
  - runtime service layer
  - persistence layer for analytics/chat lifecycle
  - separate DB session handling
  - deterministic mock report backend
  - calculation pipeline for derived metrics
  - tests across graph/runtime/API/persistence/contracts
- The current runtime is mainly report-centric.
- The existing graph is roughly:
  - resolve_scope
  - interpret_request
  - route_decision
  - run_report
  - calc_metrics
  - compose_answer
  - with exits for clarify/reject
- This means the project is already beyond an initial prototype, but it is still relatively narrow in how it answers questions.
- Right now it is strong in structure, determinism, and safety, but it is still limited in dynamic planning and flexible analytics execution.

What needs to improve
I want the next evolution of the project to move from a fixed report-first agent toward a more dynamic, controlled analytics agent.

The improved architecture should support the following ideas:
1. A typed analysis-planning layer
   - The agent should not only map a user question to a single report.
   - It should be able to build a structured analysis plan.
   - The plan should support multiple steps such as:
     - retrieve total metric
     - retrieve breakdown
     - retrieve time series
     - retrieve previous period
     - compute deltas or percent change
     - compute trend or moving average
     - rank top or bottom dimensions
     - compose final answer
   - The plan must remain typed, bounded, and deterministic enough for a production-style backend.

2. A step-based execution runner
   - The system should be able to execute a structured analysis plan step by step.
   - Intermediate results should be stored and reused in later steps.
   - Later steps should be able to reference earlier outputs safely.
   - The execution system should preserve a trace of what happened for debugging, observability, and analytics persistence.

3. A bounded internal tool registry
   - I do not want a giant uncontrolled toolbox.
   - I want a small, explicit registry of approved analytics tools.
   - These tools should represent meaningful business operations, for example:
     - fetch_total_metric
     - fetch_breakdown
     - fetch_timeseries
     - fetch_previous_period
     - compute_percent_change
     - compute_trend_slope
     - moving_average
     - rank_top_k
     - rank_bottom_k
   - The registry should be typed and discoverable by the planner/runtime.
   - Avoid overly dynamic or unsafe patterns.

4. Richer user question interpretation
   - The current interpretation should evolve beyond strict report selection.
   - The system should better understand:
     - relative time expressions like today, yesterday, last week, this month, past 30 days
     - ranking requests like top 5, worst, highest, lowest
     - comparison requests like compare with last week, versus previous month
     - trend requests like over time, trend, growth, decline
     - breakdown requests like by source, by location, by payment type
   - The interpretation layer should remain robust and typed, not overly magical.

5. Stronger scope and permission enforcement
   - Scope enforcement should not be only a yes/no grant check.
   - The runtime should verify whether requested analytics/report/tool operations are actually allowed.
   - Allowed report IDs, dimensions, metrics, and tool operations should be enforceable.
   - The system must stay safe for demo use now, but also be architected correctly for stricter permissions later.

6. Better execution-state modeling
   - The current state model should evolve to support:
     - analysis intent
     - selected metrics/dimensions/time windows
     - execution plan
     - intermediate artifacts
     - derived metrics
     - warnings
     - execution trace
     - final answer payload
   - The graph should pass structured artifacts between nodes instead of relying on loose ad hoc fields.

7. Better answer composition
   - The answer layer should remain structured and reliable.
   - But it should become more expressive than simple deterministic templating.
   - It should be able to summarize multi-step findings clearly.
   - It should be able to reference comparisons, trends, rankings, and warnings in a coherent way.
   - The system should preserve trustworthiness and avoid hallucinated claims.

8. Demo readiness plus long-term evolution
   - The plan should preserve a realistic path for short-term demo value.
   - But it should also clearly show how the project evolves toward a stronger long-term architecture.
   - The plan should explicitly separate:
     - what should be done now
     - what should be done soon after
     - what can wait until later

Important design philosophy
- Do not recommend rebuilding the entire project.
- Build on the existing good foundation.
- Prefer incremental architectural evolution.
- Preserve typed contracts, clean boundaries, deterministic components, and testability.
- Avoid turning the system into a fully open-ended raw database agent.
- Avoid generic overengineering.
- Prefer a constrained analytics agent with controlled flexibility.

What I want from you
Produce a serious implementation roadmap with strong reasoning.

Your response must include:

1. A concise diagnosis of the current architecture
   - what is already good
   - what is currently limiting growth
   - what the next architectural step should be

2. A target architecture proposal
   - describe the ideal next-stage architecture in practical terms
   - explain how the graph/runtime/planner/tools/state should fit together
   - explain why this is better than staying purely report-centric

3. A phased implementation plan
   - break the work into clear phases
   - each phase should include:
     - objective
     - why it matters
     - exact implementation direction
     - expected files/modules to introduce or update
     - risks
     - done criteria
   - make the phases realistic and engineering-friendly

4. A proposed upgraded LangGraph flow
   - suggest the next graph shape
   - show which nodes should exist
   - explain what each node is responsible for
   - explain where planning and execution should happen

5. A tool architecture plan
   - define what kinds of tools should exist
   - how they should be registered
   - how they should be invoked
   - how results should be typed and stored
   - how to keep the system bounded and safe

6. A state and contract evolution plan
   - explain how the state model should evolve
   - explain which schemas/contracts are needed
   - explain how intermediate execution artifacts should be represented

7. A persistence and observability plan
   - explain what should be stored for runs
   - explain what should be persisted from the execution trace
   - explain what warnings/failures/clarifications should look like analytically

8. A testing strategy
   - explain what unit tests, contract tests, graph tests, and integration tests should be added
   - explain how to test dynamic planning without making the system flaky

9. A prioritization summary
   - clearly mark:
     - must do now
     - should do next
     - later enhancements
   - focus on practical execution, not abstract theory

10. Explicit tradeoff analysis
   - explain what we gain and what complexity we introduce
   - explain why this is the right level of flexibility for the project

Output style requirements
- Write clearly, professionally, and concretely.
- Be detailed and structured.
- Do not give shallow generic advice.
- Do not suggest unnecessary enterprise complexity.
- Make the plan feel implementable by a real backend/AI engineering team.
- Use precise technical language, but keep it readable.
- When useful, propose module/file names and contract names.
- Assume Python backend, LangGraph orchestration, typed Pydantic contracts, FastAPI, and a report/analytics-oriented domain.

Final instruction
I do not want a vague strategic essay. I want a concrete improvement map that can directly guide implementation decisions for the next stage of the SmartRest AI agent.
