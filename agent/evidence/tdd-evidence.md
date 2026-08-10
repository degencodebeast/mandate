# Ticket 10c — TDD Evidence

Project: `mandate/.worktrees/mandate-ticket-10c/agent`
Base SHA (REST phase): `42b73d60a7032b50441d0b9b60c8f9dc5724003f`
Review base SHA (MCP phase): `311eaff65016f74c5858e68ddce8e09d2903b999`
Branch: `ticket/10c-agno-economic-safety-demo`

Ticket 12a passed its gate at `311eaff` and is merged. The demo now uses MCP
for agent spend and status, with REST as the fallback (ADR-0033).

Every behavior slice followed strict TDD: one behavior test, RED, minimum
implementation, GREEN.

## Behavior 1 — decision mapping (7 tests)

RED:

```
ModuleNotFoundError: No module named 'agno_demo'
```

Command: `uv run pytest tests/test_decisions.py -q`

GREEN:

```
7 passed in 0.01s
```

Rules proven: `UNKNOWN` -> `wait`/`request_review` with `may_authorize=False`;
`permitted`/`settled` -> `continue`; open Circuit Breaker -> `switch_service`;
policy denial -> `reduce_scope`; `accepted` -> `wait`.

## Behavior 2 — REST client (6 tests)

RED:

```
ModuleNotFoundError: No module named 'agno_demo.rest'
```

Command: `uv run pytest tests/test_rest.py -q`

GREEN:

```
13 passed (test_rest + test_decisions)
```

Rules proven: spend POSTs to the exact endpoint with bearer auth; status GETs
the status document; create_mandate POSTs to the admin endpoint; resolve POSTs
to the resolve endpoint; non-2xx raises RestError; transport errors propagate.

## Behavior 3 — scenes (2 tests)

RED:

```
ModuleNotFoundError: No module named 'agno_demo.scenes'
```

Command: `uv run pytest tests/test_scenes.py -q`

GREEN:

```
2 passed
```

Rules proven: freeze scene makes exactly one spend for Intent A on Service A,
chooses WAIT/REQUEST_REVIEW with `may_authorize=False`, and never pays Service B
for Intent A; switch scene reads the open Service A breaker, selects Service B
before authorization, completes one paid action with one Receipt Anchor, and
never pays Service A for Intent B.

## Behavior 4 — Agno agent surface (2 tests)

RED:

```
ModuleNotFoundError: No module named 'agno_demo.agent'
```

Command: `uv run pytest tests/test_agent.py -q`

GREEN:

```
2 passed
```

Rules proven: the agent has exactly tools `mandate.spend` and `mandate.status`;
it has no direct payment tool; `retries=0`, `reasoning=False`, strict
`output_schema=AgentDecision`.

## Behavior 5 — agent tools call the Mandate client (2 tests)

Command: `uv run pytest tests/test_agent_tools.py -q`

GREEN:

```
2 passed
```

Rules proven: `mandate.spend` POSTs to `/spend` and returns the structured
outcome; `mandate.status` GETs `/status` and returns breaker state.

## Behavior 6 — demo report (3 tests)

RED:

```
ModuleNotFoundError: No module named 'agno_demo.report'
```

Command: `uv run pytest tests/test_report.py -q`

GREEN:

```
3 passed
```

Rules proven: Payment Reference and Receipt Anchor are separate values; the
same Intent ID appears in the agent, backend, and UI views; the report closes
with "One Intent. No blind retries."

## Behavior 7 — MCP client (5 tests)

Ticket 12a passed, so the agent uses MCP. RED:

```
ModuleNotFoundError: No module named 'agno_demo.mcp_client'
```

Command: `uv run pytest tests/test_mcp_client.py -q`

GREEN:

```
5 passed
```

Rules proven: `mandate.spend` and `mandate.status` run through the MCP session;
a transport error on spend or status falls back to REST; a Mandate tool error
(`is_error`) propagates without the REST fallback; `resolve` uses the REST
fallback (the MCP adapter exposes spend and status only); an empty credential is
rejected.

## Behavior 8 — agent run and model provider (8 tests)

Ticket 12a passed; the demo now routes every decision through `agent.run()` with
an explicit model. RED:

```
ModuleNotFoundError: No module named 'agno_demo.providers'
```

Command: `uv run pytest tests/test_agent.py tests/test_providers.py -q`

GREEN:

```
13 passed
```

Rules proven: `build_agent` always provides a model (the deterministic
`DecisionModel` by default); an injected model is used; `run_agent_spend`,
`run_agent_status`, and `run_agent_switch` genuinely run the Agent and invoke
`mandate.spend` / `mandate.status` as real tools (the tool entrypoints call the
Mandate client, and the tests assert the client was called); the switch decision
stops when the exact Service A breaker row is not open; the OpenAI provider
fails closed without `OPENAI_API_KEY`.

## Behavior 9 — injected-response-loss gate and three-surface Intent ID

The freeze scene labels the injected condition only when the demo is configured
to inject response loss AND the service confirms it lost the response
(`injected_response_loss` on the Spend Result) AND the outcome is UNKNOWN; a
configured-but-unverified injection raises instead of labeling. The report
records the Intent identifier separately from the agent, backend, and UI
surfaces, and names the UI source (status API rendered by the dashboard)
instead of aliasing one backend value into three labels.

## Full agent suite

Command: `uv run pytest -q`

Result:

```
46 passed
```

## Run evidence

- `evidence/demo-run-mcp.txt` — both scenes through the MCP path with REST
  fallback.
- `evidence/demo-run-rest.txt` — both scenes through the pure REST fallback.

Both record the same Intent identifier in the agent, backend, and UI views,
name the UI source, and keep Payment Reference separate from Receipt Anchor.
Both runs route decisions through the deterministic Agent model, invoke
`mandate.spend` / `mandate.status` as real tools, and label the injected
response loss.
