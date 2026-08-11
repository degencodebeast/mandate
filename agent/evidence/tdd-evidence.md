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
stops when the exact Service A breaker row is not open; the switch decision
applies an UNKNOWN Service B Spend Result as WAIT or REQUEST_REVIEW with
`may_authorize=False`; only the deterministic `DecisionModel` provider is
advertised because it is the only model that can drive the scene tool plan.

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
49 passed
```

## Scripted fixture output

- `python -m agno_demo.run_demo` can create `evidence/fixture-run-mcp.txt`
  and `evidence/fixture-run-rest.txt` for local behavior checks.

These files use a scripted backend. They move no value. They are not submission
proof. A real ticket 10c run must use `python -m agno_demo.demo` against the
Mandate Service and must capture the same Intent ID, the exact Payment
Reference, the official `completed` payment state, and the matching Receipt
Anchor.

## Correction round 3 — TDD evidence for the three gate findings

### Finding 1 — real Mandate response-loss control and marker

The real Mandate backend now owns the failure control. `INJECT_RESPONSE_LOSS`
is an API-owned configuration variable. `CircleCliPaymentExecutor` runs the
real payment and then deliberately loses the response, raising
`PaymentUnknownError(injected_response_loss=True)`. The spend service threads
the marker into the UNKNOWN `SpendResponse`, and the shared
`documents.spend_document` (used by REST and MCP) renders
`injected_response_loss`. A genuine network fault carries `False`.

RED (backend): the spend document had no `injected_response_loss` key.

```
KeyError: 'injected_response_loss'
```

Command: `uv run pytest tests/test_spend_api.py -k "injected or genuine_unknown"`

GREEN:

```
2 passed
```

Also covered: `tests/test_payments.py` (15 passed) and `tests/test_config.py`
(`inject_response_loss` defaults to False and reads from environment). Backend
suite: 349 passed.

### Finding 2 — UNKNOWN Service B maps to WAIT or REQUEST_REVIEW

`decide_switch_document` now applies the Service B Spend Result before the
final decision. An UNKNOWN result for Intent B maps to WAIT or REQUEST_REVIEW
with `may_authorize=False`; the open Service A precondition never overrides it.

RED (agent): the switch decision returned `switch_service` for an UNKNOWN
Service B result.

```
assert decision.action == "switch_service"
E AssertionError: assert 'request_review' == 'switch_service'
```

Command: `uv run pytest tests/test_agent.py tests/test_scenes.py`

GREEN:

```
test_agent_switch_run_maps_unknown_service_b_to_wait_or_request_review
test_switch_scene_stops_when_service_b_result_is_unknown
```

Agent suite: 47 passed.

### Finding 3 — only the deterministic model is advertised

The `openai` provider option and extra are removed. `build_model` accepts only
`decision`; an unknown provider fails closed. The `model` injection point
remains for tests and custom deterministic models only, and the scene runner
rejects any model that cannot drive the tool plan.

RED: the old provider test expected an OpenAI path.

Command: `uv run pytest tests/test_providers.py`

GREEN: `build_model(provider="openai")` raises `ModelProviderError`.

## Correction round 2 — TDD evidence for the three gate findings

### Finding 1 — exact, one-shot response-loss control

The backend control is now exact: `INJECT_RESPONSE_LOSS_SERVICE_URL` is an
API-owned config variable naming the exact Service A URL. `CircleCliPaymentExecutor`
injects the deliberate response loss only for that exact service URL, once;
Service B and later calls behave normally. The scripted backend mirrors the
same exact selector.

RED (backend): the old boolean flag injected for every service.

```
Failed: DID NOT RAISE PaymentUnknownError
```

Command: `uv run pytest tests/test_payments.py`

GREEN:

```
37 passed
```

Rules proven: exact Service A injection once; Service B not injected; genuine
timeout carries `injected_response_loss=False`; default returns the result.

### Finding 2 — a genuine fault is never labeled injected

`CircleCliPaymentExecutor` sets `injected_response_loss=True` only on the
verified deliberate-loss path after the real economic action. Timeout and
CalledProcessError paths always raise with `injected_response_loss=False`.
Backend suite: 350 passed.

### Finding 3 — Scene B applies the full Service B Spend Result mapping

`decide_switch_document` now applies the full `decide()` mapping of the Service
B Spend Result to the post-spend decision: UNKNOWN -> WAIT/REQUEST_REVIEW
(may_authorize=False), policy denial -> REDUCE_SCOPE/REQUEST_USER
(may_authorize=False). The pre-authorization switch choice (SWITCH_SERVICE) is
recorded as separate evidence (`SceneResult.switch_choice` and
`report.switch_choice_action`). `SwitchScene` resolves only a genuinely
`accepted` paid action and never resolves a blocked, denied, or UNKNOWN Intent.

RED (agent): a policy-denied Service B result returned SWITCH_SERVICE.

```
assert decision.action == "reduce_scope"
E AssertionError: assert 'switch_service' == 'reduce_scope'
```

Command: `uv run pytest tests/test_agent.py tests/test_scenes.py`

GREEN:

```
test_agent_switch_run_maps_service_b_policy_denial_to_reduce_scope
test_switch_scene_stops_when_service_b_is_policy_denied
```

Agent suite: 49 passed.

## Correction round 3 — TDD evidence for the four gate findings

### Finding 1 — validate the payment result before marking an injected loss

`CircleCliPaymentExecutor` now parses the CLI result (`_extract_payment_result`)
before any deliberate discard. A definite rejection (explicit error or settle
failure) raises `PaymentExecutionError` on its normal path; unusable output
raises `PaymentUnknownError` with `injected_response_loss=False`. Only a
genuinely accepted payment reaches the deliberate-loss step.

RED (backend): a rejection was mislabeled injected.

```
AssertionError: assert True is False  (injected_response_loss)
```

Command: `uv run pytest tests/test_payments.py`

GREEN: 18 passed. New tests:
`test_circle_payment_executor_rejection_stays_definite_even_when_injection_configured`,
`test_circle_payment_executor_unusable_output_is_unknown_not_injected`.

### Finding 2 — durable injected-loss fact in the status record and UI

The spend service now stores `REASON_INJECTED_LOSS` as the Intent reason when
the deliberate loss occurs. `documents.intent_document` renders
`injected_response_loss` from that stored reason, so the status document carries
the durable fact. The dashboard `IntentRecord` gains `injected_response_loss`
and `EconomicSafetyCard` shows an explicit `UNKNOWN (INJECTED)` label distinct
from a genuine fault.

RED (backend): the status document had no injected marker.

Command: `uv run pytest tests/test_spend_api.py -k "durable or marks_genuine"`

GREEN: 3 passed. Dashboard tests 48 passed (new
`labels an injected response loss distinctly from a genuine fault`).

### Finding 3 — the Agent selects Service B before authorization

`SwitchScene` now calls `run_agent_switch_choice`, a separate Agent run whose
only tool is `mandate.status`: it returns SWITCH_SERVICE (or raises) before any
spend tool call, and the test proves `client.spend_calls == []`. The Service B
spend then runs as a separate Agent step (`run_agent_spend`) that maps the full
Service B Spend Result. The pre-authorization choice is recorded as separate
evidence.

RED (agent): the pre-auth choice was a pure function call in the scene.

Command: `uv run pytest tests/test_agent.py tests/test_scenes.py`

GREEN: agent suite 54 passed. New tests:
`test_agent_switch_choice_selects_service_b_before_any_spend`,
`test_agent_switch_choice_stops_when_service_a_breaker_is_closed`,
`test_agent_spend_maps_accepted_service_b_result`,
`test_agent_spend_maps_service_b_policy_denial_to_reduce_scope`.

### Finding 4 — scripted evidence obeys the production breaker policy

Scene A now starts with Service A's breaker CLOSED. The injected response loss
records a failure; when the failure count reaches `breaker_failure_threshold`
the breaker transitions to OPEN before Scene B, matching the production policy
(`policy.breaker_closed` blocks authorization while OPEN). The switch scene then
reads the open breaker. Scripted fixture output does not reuse ticket 11
evidence and does not claim a ticket 10c real action.

RED (agent): the evidence started with the breaker open.

Command: `uv run pytest tests/test_scripted_backend.py`

GREEN: 4 passed. New tests:
`test_scripted_backend_injected_loss_trips_breaker_from_closed_to_open`,
`test_scripted_backend_rejects_service_a_authorization_while_breaker_open`,
`test_scripted_backend_injected_loss_requires_closed_breaker`,
`test_scripted_backend_failure_threshold_holds_multiple_failures`.

Agent suite: 54 passed. Backend suite: 354 passed. Dashboard: 48 passed + build.

## Controller gate correction — complete Intent ID visibility

The dashboard no longer clips Intent IDs inside the service cell. The service
cell permits wrapping and visible overflow. The Intent ID permits wrapping at
any character.

RED (dashboard): the CSS regression test found the clipping rule.

```
expected '... white-space: nowrap; overflow: hidden ...'
to match /white-space:\s*normal/
```

Command: `npm test -- --run src/app/globals.test.ts`

GREEN: 1 focused test passed. The full dashboard suite passed with 51 tests.
Typecheck, lint, and the production build also passed.

The browser proof command checks each full UUID. It fails when an Intent ID
overflows its own box or crosses a clipping ancestor. It then captures the
dashboard proof image. The corrected run reported both complete UUIDs as
visible and replaced `agent/evidence/real-demo-dashboard.png`.
