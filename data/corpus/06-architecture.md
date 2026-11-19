# Northwind Analytics — Platform Architecture

## Shape

Northwind is a Python and Go monolith-plus-satellites: one Django monolith
(`services/core`) carrying the product, and four Go services around it for the
hot paths — ingestion, query, export and billing-events.

## Ingestion path

Events arrive at the Go ingestion service, which validates against a JSON schema
registry and writes to Kafka. The topic `events.raw` has 48 partitions and a
retention of 72 hours. A Flink job reads `events.raw`, deduplicates on
`(tenant_id, event_id)` over a 10-minute window, and writes Parquet to S3.

## Query path

Interactive queries go to ClickHouse. The rule of thumb is that any dashboard
query must return in under 800 milliseconds at p95; anything slower moves to the
pre-aggregation pipeline instead of being optimised in place.

## Storage boundaries

PostgreSQL holds relational product state — tenants, users, dashboards, billing.
ClickHouse holds event analytics. There are no cross-database joins; the service
that owns the data owns the query.

## Multi-tenancy

Tenancy is row-level, enforced by a `tenant_id` column plus Postgres row-level
security. There is no per-tenant database. The two Enterprise customers with
regulatory isolation requirements are served from a separate cluster in
eu-central-1, with its own Kafka and ClickHouse.

## Why not microservices everywhere

The 2024 architecture review concluded that splitting the Django monolith further
would increase the number of network calls per request from three to eleven, and
that the team of 30 engineers could not staff the operational surface. The
decision is revisited annually.
