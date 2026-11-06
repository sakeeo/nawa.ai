# ADR 0007: Self-hosted and local-first

- Status: Accepted
- Date: 2026-11-06

## Context

The target customers cannot send documents or business data to third-party AI services.
The platform must run on their hardware, including without internet access.

## Decision

- Local models are the installation default: Ollama serves the chat model and the BGE-M3
  embedding model. External providers (DeepSeek in development) are opt-in in the setup wizard
  and are not offered when `OFFLINE_MODE=true`.
- `OFFLINE_MODE=true` removes every external model from the gateway's candidate list. A call
  with no local candidate fails before any network access.
- Embeddings are always local, so switching chat providers never forces a re-index.
- No telemetry leaves the host: LiteLLM uses its bundled price map and has telemetry off,
  Langfuse runs self-hosted, and the web app loads no remote fonts and disables Next.js
  telemetry.
- Offline behaviour is verified by a unit test (no outbound socket connection in offline mode)
  and by `make offline-smoke`, which runs the stack on a Docker network with no internet route.
- Langfuse v3 is used. It needs ClickHouse, Redis, and object storage in addition to
  PostgreSQL, so it sits behind the optional `observability` profile and `make dev-lite` runs
  without it.

## Consequences

- Local model quality and latency are lower than large hosted models; the evaluation report
  measures the gap per phase.
- First install downloads several GB of model weights; offline installs need the models
  pre-pulled.
- Langfuse v3 raises the resource needs of the full stack above the minimum hardware profile;
  tracing is optional for small installs.
