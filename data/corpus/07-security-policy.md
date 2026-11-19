# Northwind Analytics — Security Policy

## Access control

Access follows least privilege and is granted through Okta groups, never to
individuals. Every group has a named owner and is reviewed quarterly; a group
whose review lapses for two consecutive quarters is automatically emptied.

Production database access requires a just-in-time grant through `nw access
request`. Grants expire after four hours and every session is recorded.

## Secrets

Secrets live in Vault. Nothing is read from an environment file in production —
the pods fetch at start-up with a short-lived token. A secret that appears in a
commit is treated as compromised even if the commit never shipped: rotate first,
investigate second.

## Dependency and image scanning

CI runs dependency scanning on every pull request and blocks merge on any
Critical finding. Container images are rescanned nightly; an image with a
Critical CVE and a published fix must be rebuilt within seven days.

## Encryption posture

Transport is TLS 1.3 with TLS 1.2 permitted only for two legacy integrations
scheduled for removal. At rest everything uses AES-256. Disk-level encryption is
not considered sufficient on its own for the audit log store, which is
additionally encrypted at the application layer.

## Penetration testing

An external penetration test runs twice a year. Findings rated High or above
block the next feature release until remediated or formally risk-accepted by the
CISO in writing.

## Phishing and device policy

All staff complete phishing training on joining and annually. Devices must have
full-disk encryption, screen lock under five minutes, and the MDM agent running.
A device missing from MDM for 14 days loses access automatically.
