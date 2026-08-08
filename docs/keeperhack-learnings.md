# KeeperHack Learnings — Distilled Wisdom Reference

This document records the key architectural and product learnings distilled from 13 winning hackathon repos in the keeper-hack workspace. Each learning maps to a Mandate ADR or design decision.

## Sources reviewed

| Project | Stack | Primary lesson applied to Mandate |
|---|---|---|
| Aegis | Node, JavaScript | Fail-closed policy engine with composable checks |
| KeeperForge | Python, FastAPI, Agno, Next.js | Advisory agent + deterministic policy gate, Privy JWT, secret boundary |
| Leash | TypeScript, React, Node | Tool policy with route/risk/approval classification |
| agent-rank / Proof Arena | Python, FastAPI, Agno | Decision-only agent invariant, InMemoryDb tests |
| Veridex Arena | Python, FastAPI, Agno | Sealed evidence, independent verification, AgentOS adapter |
| Almanak SDK | Python, gRPC, EVM/SVM | Intent compilation, least-privilege permissions |
| Maneki Hash | Python | Isolated agent fleet, persistent runtime |
| AllScale | Python | Canonical, gated execution envelope |
| Gridora | Python, Solidity, Next.js | Commit-before-trade verification |
| MonClaus | Python | Deterministic reason codes, replay, pre-live promotion |
| Neural Alpha | TypeScript, Next.js | Production monitoring, code-enforced portfolio risk |
| quantpylib | Python, C++ | Common gateway, OMS, feed, simulator, venue adapters |
| The Gauntlet | TypeScript, Next.js | Risk-adjusted tournaments, anti-gaming |
| Guarded Alpha | Python, TypeScript | Multi-signal voting, hard risk governor, proof ledger |

## 1. Policy engine: check(ctx) → { allow, reason } (Aegis)

Every check is a pure function. Aegis composes them with AND semantics. "No policies = god-mode" — throw `MissingPolicyConfigError`. Mandate implements: `mandate-active`, `budget-remaining`, `per-call-cap`, `intent-dedupe`, `service-allowlist`, `circuit-breaker`. → ADR-0021

## 2. Advisory agent + deterministic policy (KeeperForge)

KeeperForge separates the LLM review (ENDORSE/ABSTAIN/FLAG — advisory) from `_apply_policy` (ALLOW/DENY — deterministic). The agent suggests; the gate decides. Mandate follows: the agent reasons about what to buy; the mandate gate deterministically decides whether to allow it. → ADR-0021

## 3. AgnoTradeReviewAdapter: decision-only agent (KeeperForge)

`Agent(output_schema=AgentReviewOutput, reasoning=False, retries=0, tools=[])`. The agent cannot call any external service. It produces a structured verdict only. Mandate's agent uses the same pattern — it reasons, but it cannot pay. Payment goes through `mandate.spend`. → ADR-0022

## 4. PolicyContext + PolicyResult dataclasses (KeeperForge)

Frozen `PolicyContext` passed to `_apply_policy`. Frozen `PolicyResult` with `decision`, `rule`, `observed_value`, `allowed_value`. Mandate uses frozen `SpendContext` and `SpendResult` with the same shape. → ADR-0021, CONTEXT.md

## 5. PipelineResult outcomes (KeeperForge)

`outcome: agent_review_stopped | denied_before_keeperhub | permitted`. Clear, named outcomes. Mandate's outcomes: `blocked: duplicate_intent | budget_exceeded | breaker_open | service_not_allowed | mandate_expired` or `permitted`. → spec

## 6. Fail-closed on missing credential (KeeperForge)

KeeperForge disables a connection for fault if the credential is missing, rather than proceeding. Mandate fails closed if the service is unavailable. → ADR-0018

## 7. Idempotency-Key header (KeeperForge)

KeeperForge's `IntervalEvaluationRequest` requires an `Idempotency-Key` header. Rejects if missing, too long (>512), too short, or contains whitespace. Mandate's purpose hash doubles as the idempotency key. → ADR-0023

## 8. ToolPolicy: route, risk, approval (Leash)

Leash classifies tools by risk (read, low_write, write, device_control, shell, network, admin) and approval requirements (none, required). `mandate.spend` is `risk: write, approval: required` — every payment is a write operation requiring mandate-backed approval. Leash's `argsHash` binds an approval to specific tool args — Mandate's purpose hash does the same. → CONTEXT.md (Spend Context), spec

## 9. Decision-only invariant (agent-rank)

`Agent(tools=[])` is a hard invariant. Agents produce decisions, not actions. The execution layer decides whether to act. Mandate follows: the LLM agent reasons; the policy gate decides. → ADR-0022

## 10. InMemoryDb + scripted adapters for tests (Veridex, KeeperForge)

Veridex uses `InMemoryDb` and `InMemoryStore` — no network. KeeperForge uses `ScriptedTradeReviewAdapter` and `DeterministicTradeReviewAdapter` for controlled LLM responses. Mandate tests use the same pattern. → ADR-0024

## 11. One narrow, undeniable execution loop (distilled docs)

The hackathon demo should show: "one real payment through the gate, one rejected duplicate, one tripped circuit breaker, and one on-Arc receipt." Not a platform tour — a narrow loop that proves the concept. → spec (demo arc), README

## 12. Governance flow: bounded config → policy → execution → receipt (distilled docs)

`BOUNDED CONFIGURATION → VERSIONED SPEC → POLICY CHECK → EXECUTION → RECEIPT + PROOF`. Mandate's flow: `MANDATE → SPEND (policy check) → CIRCLE NANOPAYMENT → RECEIPT (on Arc)`. → README, spec

## 13. Make the sponsor central (distilled docs)

KeeperForge made KeeperHub central. Mandate makes Circle + Arc central — the payment flows through Circle Nanopayments on Arc, and the receipt lives on Arc. Arc is not decorative. → README, ADR-0006

## 14. Zone isolation for Alpine appliances (Almanak SDK)

Not directly applicable beyond the ADR-0018 fail-closed principle and the security-by-separation pattern encoded in ADR-0011.

## 15. The pitch line (distilled docs)

"Agents can pay. Mandate makes them pay safely — within budgets, without duplicates, with receipts on Arc." → README