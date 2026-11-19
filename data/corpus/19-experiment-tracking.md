# Northwind Analytics — Experiment Tracking Conventions

The ML platform document covers models in production. This one covers the
experiments that never ship, which is most of them.

## One run, one commit

Every run logs the git SHA, the dataset version hash, the full parameter set and
the environment lockfile hash. A run missing any of the four is tagged
`unreproducible` automatically and excluded from any comparison table.

## Naming

Runs are named `<initials>-<ticket>-<short-hypothesis>`. The hypothesis is
mandatory and must be falsifiable: "lower LR stabilises late epochs" is
acceptable, "tuning" is not.

## What gets logged

Parameters, metrics per epoch, the confusion matrix, five sampled wrong
predictions, and wall-clock plus accelerator hours. Sampled errors are the field
people skip and the one that most often explains a metric.

## Comparison discipline

Two runs may only be compared if the dataset version hash matches. The tracking
server blocks a comparison view across differing dataset hashes, after a quarter
in which a 4-point "improvement" turned out to be a changed test split.

## Retention

Experiment runs are kept 18 months. Artifacts larger than 2 GB are kept 90 days
unless the run is tagged `promoted`, in which case artifacts are kept as long as
the model version exists.

## Promotion handoff

A promoted run must link its tracking run ID in the model registry entry. The
registry rejects a version whose linked run is tagged `unreproducible`, which is
the mechanism that keeps the production story auditable rather than the policy
that asks people to be careful.
