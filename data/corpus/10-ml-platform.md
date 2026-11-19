# Northwind Analytics — ML Platform Conventions

## What is in production

Two models serve production traffic: an anomaly-detection model on event streams
and a text classifier that routes support tickets. Both are versioned artifacts
in the model registry; nothing is loaded from a notebook or an engineer's bucket.

## Training and tracking

Every training run is logged to the tracking server with its parameters,
metrics, dataset version and git SHA. A run that cannot be tied back to a commit
is not promotable, regardless of how good the metric looks.

## Promotion gates

A candidate model is promoted only if it beats the incumbent on the frozen
holdout set and does not regress any of the three fairness slices tracked for
the ticket classifier. Promotion is a two-person decision: the model owner and
one reviewer outside the team.

## Monitoring

Served models emit prediction distributions hourly. Drift is measured as
population stability index against the training distribution; a PSI above 0.2
opens a warning and above 0.3 pages the owning team. Label delay on the anomaly
model is roughly 48 hours, so accuracy in production is always evaluated on a
trailing window, never same-day.

## Retraining

The ticket classifier retrains monthly on a rolling 12-month window. The
anomaly model retrains on drift signal rather than on a schedule, because its
traffic mix changes with customer onboarding rather than with the calendar.

## Rollback

A model rollback is the same mechanism as a service rollback and has the same
five-minute target. The previous two versions are always kept warm.
