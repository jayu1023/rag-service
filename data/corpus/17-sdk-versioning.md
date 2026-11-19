# Northwind Analytics — Client SDK Versioning

The public API guidelines govern the HTTP surface. The SDKs are versioned
separately and the rules are not the same.

## Semantic versioning

SDKs follow semver strictly. The SDK major version is independent of the API
version: SDK 3.x may speak `/v2/`. Pinning advice to customers is a caret range
on minor, never a floating major.

## Support window

Each SDK major is supported for 12 months after its successor, half the 24-month
window the HTTP API gets. The reason is maintenance cost across five languages,
not a judgement about customer readiness.

## Languages

Northwind ships SDKs for Python, TypeScript, Go, Java and Dart. The Dart SDK is
generated from the OpenAPI document; the other four are hand-written wrappers
over a generated transport layer, because the ergonomics customers complain
about are never in the transport.

## Deprecation mechanics

A deprecated SDK method emits a warning at call time for one minor version, then
is removed in the next major. Removal in a minor version has happened once, for
a method that leaked a token into a log, and was treated as a security fix.

## Release process

SDK releases are automated from a tag. A release requires a changelog entry,
the generated client regenerated against the current OpenAPI document, and the
integration test suite passing against `staging`.

## Breaking change budget

The SDK team allows itself one breaking major per language per year. Anything
beyond that needs the API product owner's sign-off, because churn in the SDK is
paid for by every customer, not by Northwind.
