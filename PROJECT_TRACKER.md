# Nesting Sandbox Project Tracker

This tracker intentionally avoids timeframes.

The operating principle for the product is:

1. Box 1 is the required base case for every run.
2. Every other layer is optional and must justify its cost by amplifying, pressure-testing, or specializing the base-box result.
3. The product should always explain what Box 1 concluded on its own and what the optional layers added.

## Foundation Pass

- `[done]` Make the run topology explicit: Box 2 is now an optional amplification layer instead of an assumed default.
- `[done]` Reflect the topology in the UI: the mobile portal now exposes a base-box run versus a layered run.
- `[done]` Re-center reporting on Box 1: results now start with a base-box outcome summary and then show amplifier contributions.
- `[done]` Persist the top-line outcome into run history so cross-run memory carries the base result forward.
- `[done]` Tighten baseline security posture with scoped CORS configuration instead of wildcard origins.

## Product Tracks

### 1. Base Box Quality

- `[done]` Treat Box 1 as the required solver/explorer/analyst in prompts and reporting.
- `[active]` Tune prompts so Box 1 always returns a self-contained top-line answer, not just a stream of findings.
- `[active]` Improve Box 1 outcome extraction so the system can distinguish decisive conclusions from partial progress.
- `[next]` Add evaluation fixtures that compare base-box output quality against layered runs on the same prompt set.

### 2. Optional Layer Value

- `[done]` Make Box 2 optional per run.
- `[active]` Measure optional-layer contribution explicitly in the final report.
- `[next]` Suggest whether Box 2 is warranted before launch based on complexity, ambiguity, and desired confidence.
- `[next]` Add specialist suggestions based on the question, uploaded documents, and prior runs.
- `[next]` Add marginal-value stopping logic so optional layers shut down when they stop adding meaningful signal.

### 3. Output Trust

- `[done]` Add a top-line summary that separates base-box takeaways from amplifier takeaways.
- `[active]` Track and display source footprint counts: documents, web-search events, seed runs, user injections, conflicts.
- `[next]` Add citation-grade provenance so major claims show whether they came from uploaded docs, live web lookups, or inference.
- `[next]` Surface unresolved contradictions as first-class outcome objects, not just feed events.
- `[next]` Add confidence language that is driven by evidence quality, disagreement, and completion state.

### 4. Run Topology and UX

- `[done]` Build a browser-first mobile portal with stronger hierarchy and clearer launch flow.
- `[done]` Add an explicit run-topology selector to choose base-only versus layered runs.
- `[done]` Make the live visualization degrade cleanly for base-only runs.
- `[next]` Add launch presets for common intents such as investigate a claim, pressure-test a plan, and explore an impossible idea.
- `[next]` Add a “why this layer exists” explanation for specialists and spawned boxes.

### 5. History and Cross-Run Memory

- `[done]` Save the base-box primary outcome into history.
- `[done]` Seed future runs with prior primary outcomes as well as key findings.
- `[active]` Favor Box 1 findings when extracting reusable cross-run memory.
- `[next]` Add run comparison views that show how the base-box answer changed across attempts.
- `[next]` Let users fork a prior run into a new base-only or layered topology.

### 6. Reliability and Operations

- `[done]` Preserve completed run summaries and expose them via the history API.
- `[active]` Keep the current in-memory orchestration stable while the product model is clarified.
- `[next]` Move long-lived run state and event logs to durable storage.
- `[next]` Add resumable or replayable runs instead of relying on live in-memory state alone.
- `[next]` Add structured observability around run topology, layer contribution, failure modes, and costs.

### 7. Security and Multi-User Readiness

- `[done]` Replace wildcard CORS with configured origins.
- `[next]` Add authenticated users and per-user run isolation.
- `[next]` Move away from raw API-key entry toward safer provider account or server-managed credential flows.
- `[next]` Add rate limits and abuse controls on run creation, websocket sessions, and file upload paths.

## Current Definition Of Better

The product is better when all of the following are true:

- A base-box-only run is useful on its own.
- Optional layers are clearly optional in the product and the architecture.
- The final result explains what Box 1 concluded before showing any amplification.
- Users can see what the extra layers added and decide whether the extra cost was worth it.
- Previous runs preserve the top-line outcome in a form that is reusable.
