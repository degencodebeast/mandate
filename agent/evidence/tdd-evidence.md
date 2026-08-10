# Ticket 10c — TDD Evidence

Project: `mandate/.worktrees/mandate-ticket-10c/agent`
Base SHA: `42b73d60a7032b50441d0b9b60c8f9dc5724003f`
Branch: `ticket/10c-agno-economic-safety-demo`

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

## Behavior 5 — agent tools call REST (2 tests)

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

## Full agent suite

Command: `uv run pytest -q`

Result:

```
20 passed
```
