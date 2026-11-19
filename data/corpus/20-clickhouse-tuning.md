# Northwind Analytics — ClickHouse Tuning Notes

The architecture document says interactive queries go to ClickHouse. This is the
operational detail behind that sentence.

## Table design

Event tables use `MergeTree` ordered by `(tenant_id, toStartOfHour(ts),
event_name)`. Tenant first is non-negotiable: every query is tenant-scoped, so
leading with tenant turns the common case into a single range scan.

Partitioning is by month, not day. Daily partitions produced too many parts and
pushed merge pressure into query time; monthly cut part count by an order of
magnitude.

## Projections and pre-aggregation

Dashboards that exceed the 800 millisecond p95 budget get a projection or a
materialised view rather than a query rewrite. The rule is that a dashboard query
may read at most 2% of the rows in its time range; past that it needs
pre-aggregation.

## Memory

`max_memory_usage` is capped per query at 10 GB and queries are killed rather
than allowed to spill, because a spilling query degrades every other tenant on
the node. A killed query returns a specific error the dashboard surfaces as
"narrow your time range".

## Replication and backups

Three replicas per shard, two shards. Backups are taken nightly to S3 with a
14-day window; a full restore has been exercised twice and takes about four
hours for the current data volume.

## Compression

The event payload column uses `ZSTD(3)`. Moving from LZ4 to ZSTD(3) cut storage
roughly 31% at a measured 6% cost in scan throughput, which was accepted because
storage, not CPU, was the budget constraint.

## What is deliberately not done

No `FINAL` in production queries, no `OPTIMIZE TABLE` on a schedule, and no
cross-shard joins. All three have been tried and all three moved the p95 in the
wrong direction.
