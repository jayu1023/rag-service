# Northwind Analytics — Deployment Policy

## Environments

Northwind runs four environments: `dev`, `staging`, `canary` and `production`.
`canary` serves 5% of production traffic and shares the production database.

## Release train

Deploys to production happen on a release train that leaves twice a day, at
09:00 UTC and 15:00 UTC. Anything merged to `main` before the cutoff (30 minutes
before departure) rides that train.

## Canary rules

Every production release sits in `canary` for a minimum of 45 minutes. The
release is blocked from promotion if, during that window, the canary error rate
exceeds the baseline by more than 0.5 percentage points, or p99 latency
regresses by more than 20%.

## Freeze windows

There is a deploy freeze from 1 December to 2 January, and on the last two
business days of every quarter. Freezes may be overridden only by the on-call
incident commander, and only for a Sev-1 fix.

## Rollback

Rollback is a single command: `nw release rollback <version>`. The target for a
rollback is five minutes from decision to traffic restored. Rollbacks never
require a code review; the postmortem covers them after the fact.

## Database migrations

Migrations must be backward compatible for one release. The rule is expand,
migrate, contract — never drop a column in the same release that stops writing
to it. Destructive migrations require sign-off from the Data team lead.
