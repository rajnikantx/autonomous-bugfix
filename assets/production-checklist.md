# Production Checklist

## Observability & Tracing

- [ ] Every LLM call traced with input/output tokens, latency, and cost
- [ ] Every tool invocation logged with args, result, and duration
- [ ] Session-level traces linking all nodes from clone to merge
- [ ] Structured logging with correlation IDs (session_id + bug_id)
- [ ] Metrics dashboard: success rate, escalation rate, avg time/cost per bug
- [ ] Alerting on high escalation rates, long-running sessions, or cost spikes

## LLM Reliability

- [ ] Structured output validation -- Pydantic parse failures retried automatically
- [ ] Fallback model configuration if primary model is rate-limited or down
- [ ] Token usage tracked per agent per session with hard spending limits
- [ ] Prompt versioning -- pin versions, track which prompt produced which result
- [ ] ReAct loop timeout -- kill investigator after N minutes, not just N steps
- [ ] Output guardrails -- validate LLM responses match expected schema

## Sandboxing & Security

- [ ] Docker containers for code execution with network isolation
- [ ] Resource limits on sandbox (CPU, memory, disk, execution time)
- [ ] Read-only mounts where possible, write only to designated output dirs
- [ ] Secrets never enter sandbox environment
- [ ] Sandbox cleanup on crash, timeout, and SIGTERM
- [ ] API key rotation policy (every 48h)
- [ ] Prompt injection protection -- sanitize inputs reaching LLM prompts
- [ ] Circuit breakers on external API calls (OpenAI) with fallback behavior

## State Management

- [ ] Durable state storage (Redis/PostgreSQL) for session persistence
- [ ] Checkpoint/resume capability at each node boundary
- [ ] Idempotent node operations -- safe to retry on partial failure
- [ ] Concurrent session handling with proper isolation

## Testing & Evaluation

- [ ] Eval suite with known buggy repos and expected fixes
- [ ] Unit tests for all tools (code_search, file_ops)
- [ ] Integration tests for agents with mocked LLM responses
- [ ] Regression tests -- production failures converted to eval cases
- [ ] CI gate -- block merges if eval scores drop below threshold
- [ ] Load testing for concurrent sessions
- [ ] Chaos testing -- simulate LLM API failures, timeouts, tool errors

## Cost & Performance

- [ ] Per-session token budget with hard limit
- [ ] Cost alerts at configurable thresholds ($1, $5, $20 per session)
- [ ] Model selection strategy -- cheaper models for simple tasks
- [ ] Total workflow timeout (not just per-node)
- [ ] Sandbox disk usage monitoring for large codebases
- [ ] LLM response caching where applicable (triage, review)

## Deployment

- [ ] Dockerized deployment with pinned base images (sha256 digest)
- [ ] Health check endpoint for orchestrator service
- [ ] Graceful shutdown -- drain in-flight requests before terminating
- [ ] Blue-green or canary deployment strategy
- [ ] Rollback plan -- keep last 3 known-good image tags
- [ ] Kubernetes resource limits if deployed on K8s

## Human Oversight

- [ ] Optional approval gate before merging fixes to production repos
- [ ] Audit trail of all automated changes with before/after diffs
- [ ] Escalation notification (Slack/email) on auto-resolved bugs
- [ ] Ability to revert all changes from a session in one operation
- [ ] Graceful degradation -- partial fixes applied if some nodes fail

## Git Safety

- [ ] Never force-push or rewrite history
- [ ] Never delete files -- only modify or create
- [ ] Commit messages include session_id and bug_id for traceability
- [ ] Branch protection -- fixes applied to feature branch, not main directly

## Code Quality

- [ ] Type checking passes (mypy or pyright) with zero errors
- [ ] Linting passes (ruff) with zero warnings
- [ ] Pre-commit hooks for formatting and linting
- [ ] Dependency scanning (Dependabot/Snyk) for vulnerabilities
- [ ] Lock file (uv.lock) committed and up to date

## Operational

- [ ] Runbooks for common failure modes (LLM down, sandbox full, test flaky)
- [ ] Data retention policy for session logs, traces, and sandboxes
- [ ] Incident response plan for production failures
- [ ] Model drift monitoring -- track fix quality over time
