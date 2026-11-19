# Northwind Analytics — Support Escalation Path

## Tiers

Support runs three tiers. Tier 1 handles configuration and how-to questions,
Tier 2 handles product defects with a known workaround, and Tier 3 is
engineering. The routing between Tier 1 and Tier 2 is done by the text
classifier described in the ML platform document, with a human override that is
used on roughly 8% of tickets.

## Response targets

Enterprise: first response within one hour, 24/7. Business: four business hours.
Self-serve: one business day. These are response targets, not resolution
targets, and support is measured on them separately.

## Escalating to engineering

A Tier 3 escalation requires a reproduction, the tenant ID, the time window and
the request IDs. An escalation without request IDs is returned to Tier 2 — not as
a formality, but because the trace is what makes the next 20 minutes productive
instead of speculative.

Escalations land in the owning team's queue, not with on-call. On-call is for
pages, not for tickets. The only exception is a suspected Sev-1, which is
declared as an incident instead of escalated.

## Customer-reported security issues

Anything that smells like a security issue skips the tiers entirely and goes to
the security channel within 15 minutes, even if Tier 1 believes it is a
misunderstanding. False positives here cost minutes; a missed one costs the
audit.

## Feedback loop

Every month the top five escalation causes are reviewed with the owning teams. A
cause that appears in three consecutive months becomes a committed engineering
item, which is the mechanism that keeps support volume from being treated as
someone else's problem.
