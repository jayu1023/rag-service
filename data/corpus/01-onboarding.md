# Northwind Analytics — Engineering Onboarding

Northwind Analytics is a fictional company. This corpus exists so the RAG service
has a ground-truth document set whose answers cannot be guessed from an LLM's
pretraining — every fact below is invented.

## Day one

New engineers are issued a laptop with the `nw-dev` bootstrap image. Run
`nw bootstrap` once; it installs the toolchain and registers your SSH key with
the internal Git host. Bootstrap takes about 40 minutes.

Accounts are provisioned by the Platform team within one business day. If your
Okta account is missing after 24 hours, file a ticket in `#help-platform`.

## The buddy system

Every new hire is paired with an onboarding buddy for their first 30 days. The
buddy owns two things: answering questions within one hour during working hours,
and reviewing the new hire's first five pull requests.

## First commit target

Northwind expects a new engineer's first merged pull request within five working
days. It does not have to be meaningful — a typo fix counts. The point is to
prove the whole pipeline works on your machine before you need it under pressure.

## Working hours and timezones

Engineering spans three hubs: Ahmedabad (IST), Lisbon (WET) and Austin (CST).
The mandatory overlap window is 13:00–16:00 UTC. All recurring meetings must be
inside that window; anything outside it must be async.
