# Northwind Analytics — Feature Flags

## Flag types

Northwind recognises three kinds of flag, and conflating them is the usual cause
of flag debt:

- **Release flags** — hide unfinished work. Lifetime: until the feature ships.
- **Experiment flags** — split traffic for a measured test. Lifetime: the
  experiment window plus seven days.
- **Operational flags** — kill switches and load shedding. Lifetime: permanent,
  and they are the only permanent kind.

## Lifetime enforcement

Every flag is created with a type and an owner. Release and experiment flags get
an expiry date at creation, defaulting to 60 days. An expired flag opens a
blocking issue against its owner, and the tooling will not let the quarter close
with an expired release flag in the codebase.

## Defaults

A flag's default is always the current production behaviour, so a configuration
service outage degrades to "what was already happening" rather than to a
half-finished code path.

## Evaluation

Flags evaluate locally against a snapshot refreshed every 30 seconds. No request
blocks on the flag service. A stale snapshot is acceptable; a request waiting on
a network call to decide whether to render a button is not.

## Flags and billing

Any flag that can change what a customer is charged requires two approvals and
is recorded in the audit log on every change, with the previous and new value and
the actor. Billing flags may not be changed during a deploy freeze.

## Cleanup

Removing a flag means removing both branches and the test that covered the dead
one. A "cleanup" pull request that leaves the flag read but always true is
rejected at review.
