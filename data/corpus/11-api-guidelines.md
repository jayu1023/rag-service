# Northwind Analytics — Public API Guidelines

## Versioning

The public API is versioned in the path: `/v1/`, `/v2/`. A major version is
supported for 24 months after its successor ships, and the sunset date is
published the day the successor goes GA — not later.

Additive changes do not bump the version. Removing a field, changing a type, or
tightening validation does.

## Pagination

All list endpoints are cursor-paginated. Offset pagination was removed in v2
after it produced duplicate rows for customers writing during a page walk. The
default page size is 50 and the maximum is 500.

## Errors

Errors return an RFC 9457 problem document with a stable machine-readable
`type`. Error message text may change without a version bump; `type` may not.

## Rate limits

The default limit is 600 requests per minute per tenant, burstable to 1200 for
60 seconds. Limits are returned on every response in the `RateLimit-*` headers
so clients never have to guess. Exceeding the limit returns 429 with
`Retry-After`.

## Idempotency

Every write endpoint accepts an `Idempotency-Key` header, and keys are retained
for 24 hours. Replaying a key returns the original response, including the
original status code.

## Webhooks

Webhooks are signed with HMAC-SHA256 and retried with exponential backoff for
up to 24 hours. A consumer endpoint failing for seven consecutive days is
disabled and its owner emailed.
