# Northwind Analytics — Data Retention and Privacy

## Retention periods

- Raw event data: 90 days in hot storage, then 400 days in cold storage.
- Aggregated metrics: retained indefinitely.
- Application logs: 30 days.
- Access audit logs: seven years, immutable.

## Customer deletion requests

A verified deletion request must be fully satisfied within 30 days. The deletion
pipeline runs nightly and covers hot storage, cold storage, search indexes and
the analytics warehouse. Backups are the exception: they are not edited, and
instead age out on their own 35-day cycle.

## PII in non-production

Production data may never be copied into `dev` or `staging` unedited. The
`nw anonymize` tool replaces names, emails and IP addresses with deterministic
pseudonyms so joins still work across tables.

## Encryption

Data is encrypted with AES-256 at rest and TLS 1.3 in transit. Customer-managed
keys are available on the Enterprise plan only. Key rotation is automatic every
180 days.

## Sub-processors

Any new sub-processor that touches customer data needs a DPA on file and 30 days
of advance notice to Enterprise customers before it goes live.
