# Northwind Analytics — Testing Standards

## The shape of the suite

Northwind targets a pyramid, not an hourglass: roughly 70% unit, 20%
integration, 10% end-to-end. The absolute numbers matter less than the rule that
end-to-end tests are a budget, not a goal — the suite is capped at 60 E2E tests
and adding one means justifying or deleting another.

## Coverage

There is no global coverage gate, because a global number rewards testing the
easy code. Instead, `services/ledger/` and the authentication module require 90%
line coverage, enforced per-directory. Everywhere else, the review question is
"is there a test that fails if this logic breaks?"

## Flaky tests

A test that fails twice in a week without a related code change is quarantined
automatically and an issue is filed against its owning team. A quarantined test
that is not fixed within 14 days is deleted. Keeping a known-flaky test running
is worse than having no test, because it teaches people to re-run CI on red.

## Fixtures and data

Integration tests run against real Postgres and real Kafka in Docker, not fakes.
ClickHouse is the exception — it is faked at the query-builder boundary because
spinning it up costs 40 seconds per suite.

## CI timing

The full pull-request suite must finish in under 12 minutes. When it crosses
that, the fix is parallelisation or deletion, never "wait longer".

## Performance tests

Load tests run nightly against `staging` at 2x expected peak. A regression of
more than 15% in p95 on any flagged endpoint opens a blocking issue.
