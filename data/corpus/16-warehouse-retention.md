# Northwind Analytics — Warehouse and Derived Data Retention

The privacy document covers customer-facing retention commitments. This one
covers internal derived data in the analytics warehouse, where the numbers are
different and frequently confused.

## Layers

The warehouse has three layers: `raw` (a copy of ingested Parquet), `staged`
(cleaned and typed), and `marts` (business tables). Raw is kept 180 days,
staged 400 days, marts indefinitely.

Note the mismatch that trips people up: hot event storage is 90 days in the
product, but the warehouse `raw` copy is 180. Both are in scope for a customer
deletion request.

## Derived tables and deletion

A deletion request propagates to the warehouse through the nightly pipeline. Any
mart that cannot be rebuilt from scratch within 24 hours must carry a
`tenant_id` column so rows can be deleted surgically. A mart without one is an
audit finding.

## Sandboxes

Analysts get a personal schema with a 30-day table expiry, enforced by the
warehouse, not by convention. Nothing in a personal schema is backed up and
nothing in it may be read by a dashboard.

## Cost coupling

Warehouse storage is the second largest line in the data team's budget. The
retention numbers above were set by cost, not by policy: dropping `raw` from 400
days to 180 saved roughly 22% of warehouse storage spend and removed no
capability anyone was using.

## Reprocessing

Backfills run against `raw`, which is why `raw` exists at all. Once a backfill
window older than 180 days is needed, the source of truth is the S3 Parquet in
cold storage and the job runs offline.
