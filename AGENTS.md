# Agent Instructions

## Language Standard

Only report to the user in ASD-STE100 Simplified Technical English.

Rules:
- Use short sentences. Each sentence has one idea.
- Use active voice. Use the present tense.
- Use one word for one concept. Do not use synonyms.
- Do not use jargon unless it is defined in CONTEXT.md.
- Give the recommended answer first, then the reasons.
- For each recommendation, tell why it is the recommendation and why the other options are not.

## Agent skills

### Issue tracker

Local markdown files under `.scratch/`. See `docs/agents/issue-tracker.md`.

### Triage labels

Default five-role labels kept as-is. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: root `CONTEXT.md` + `docs/adr/`. See `docs/agents/domain.md`.
