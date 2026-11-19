# Northwind Analytics — Cloud Cost Controls

## Budget ownership

Each of the five engineering teams owns a monthly cloud budget. Spend is tagged
by `team` and `service`; anything untagged is charged to the Platform team,
which is deliberately unpleasant and has kept untagged spend under 2%.

## Alerting

A team is alerted at 80% of monthly budget and again at 100%. Crossing 120%
requires a written note to the VP of Engineering explaining the cause and the
plan — not a request for more budget.

## The biggest levers

In the 2025 review, the three largest line items were ClickHouse storage,
Kafka inter-AZ transfer, and GPU inference for the anomaly-detection model. The
first lever pulled was Kafka: moving the Flink consumer into the same AZ as the
leader partitions cut transfer cost by 38% in one week with no code change.

GPU inference was second. Batching requests to a 50-millisecond window and
caching embeddings for repeated payloads cut inference spend by just over half.
Model size was deliberately not touched first, because quality regressions are
far more expensive than instances.

## Idle resources

Non-production environments scale to zero outside 06:00–20:00 in the owning
team's timezone. Any instance running for more than 14 days with under 5% CPU is
flagged weekly and must be justified or terminated.

## Commitments

Northwind holds one-year savings plans covering roughly 60% of steady-state
compute, never more — leaving headroom has been cheaper than being locked into
a shape the architecture outgrew.
