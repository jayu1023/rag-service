# Northwind Analytics — On-call and Incidents

## Rotation

On-call is a one-week rotation, handing over on Wednesday at 10:00 UTC. Each
rotation has a primary and a secondary. The secondary is paged only if the
primary does not acknowledge within 10 minutes.

On-call engineers receive a stipend of 400 USD per week served, and are expected
to carry no more than 50% of their normal sprint load.

## Severity levels

- **Sev-1** — customer data loss or full outage. Page immediately, incident
  commander assigned, status page updated within 15 minutes.
- **Sev-2** — a major feature is broken for a subset of customers. Response
  within 30 minutes during working hours.
- **Sev-3** — degraded performance, no functional loss. Handled next business day.

## Postmortems

Every Sev-1 and Sev-2 gets a written postmortem within three business days.
Postmortems are blameless and are published to the whole company, not just
engineering. A postmortem without at least one action item that has an owner and
a date is considered incomplete.

## Paging budget

If a single service pages on-call more than four times in one rotation, that
service goes on the reliability backlog and feature work on it stops until the
paging rate drops below the threshold. This rule has no exceptions.
