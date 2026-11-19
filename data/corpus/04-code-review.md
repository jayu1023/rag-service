# Northwind Analytics — Code Review Standards

## Size

Pull requests should stay under 400 changed lines. Anything larger must either
be split or come with a written reason in the description. Reviewers are
explicitly allowed to decline to review an oversized PR.

## Turnaround

First review feedback is expected within four working hours. If a PR has had no
review for a full working day, the author may escalate in `#eng-review`.

## Approvals

Two approvals are required for changes to billing, authentication, or anything
under `services/ledger/`. Everything else needs one approval. Approving your own
PR is blocked by tooling.

## What reviewers must check

1. Does it do what the description says?
2. Is there a test that fails if the logic breaks?
3. Are errors handled where data loss is possible?
4. Does it leak secrets, PII, or customer identifiers into logs?

Style is not a review topic — `nw fmt` runs in CI and its output is final.

## Stale branches

Branches with no commits for 30 days are deleted automatically. The tooling
warns the author seven days before deletion.
