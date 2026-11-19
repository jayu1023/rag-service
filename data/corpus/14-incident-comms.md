# Northwind Analytics — Incident Communication

This covers what is said to whom during an incident. The severity ladder and
paging mechanics live in the on-call document; this one is only about comms.

## Roles

An incident has three named roles: the incident commander, the comms lead and
the scribe. The commander never writes customer-facing updates — splitting those
two jobs came out of a 2024 incident where the fix stalled for 25 minutes while
the commander wrote a status post.

## Status page

For a Sev-1 the status page is updated within 15 minutes and then every 30
minutes until resolution, even when there is nothing new to say. "Still
investigating, next update by HH:MM" is a valid update and is preferred over
silence.

## Customer email

Enterprise customers with an uptime commitment get a direct email within two
hours of a Sev-1 being declared, sent by the account team using the comms lead's
copy. Self-serve customers get the status page only.

## Internal channel

Each incident gets a dedicated channel named `inc-YYYYMMDD-short-slug`. All
decisions are written there, not in DMs. The scribe pins a running timeline.

## What is never said

Northwind does not publish a root cause while the incident is open, does not
name individual engineers in any customer-facing text, and does not give an ETA
for resolution unless the fix is already verified in staging.

## After resolution

The comms lead posts a resolution note within one hour of recovery and links the
postmortem once it is published. Regulatory notification, when the incident
involved personal data, is handled by Legal within 72 hours.
