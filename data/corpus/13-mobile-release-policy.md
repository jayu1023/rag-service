# Northwind Analytics — Mobile Release Policy

This is the mobile counterpart to the backend deployment policy, and it is
deliberately different because app stores are not a deploy target you control.

## Cadence

The Northwind mobile app ships on a two-week train, cutting on alternate
Tuesdays at 11:00 UTC. Unlike the backend release train, a missed mobile cut
means waiting a full fortnight, so the cut is never moved for a single feature.

## Staged rollout

Android releases go out at 5% for 24 hours, 20% for a further 48 hours, then
100%. iOS uses phased release over seven days. Promotion is halted if the
crash-free session rate drops below 99.5% or if the store rating over the
rollout window falls below 4.2.

## Minimum supported versions

The app supports the current and previous two major OS versions. Dropping
support requires 90 days of in-app notice to affected users.

## Forced upgrade

The app can force an upgrade through a server-side kill switch. It is reserved
for a security fix or a broken API contract, has to be approved by the mobile
lead and the on-call incident commander, and is never used to push a feature.

## Hotfixes

A mobile hotfix still goes through review, so the realistic floor is 24 hours on
Android and 48 on iOS. Anything that must be fixed faster has to be fixable from
the server — which is why feature flags are mandatory for any screen touching
billing or authentication.

## Rollback

There is no mobile rollback. The previous build is re-promoted on Android and a
new build is expedited on iOS. This asymmetry with the backend five-minute
rollback target is the main reason risky changes are gated server-side.
