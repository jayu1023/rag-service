# Northwind Analytics — Contractor and Vendor Access

The general security policy covers staff. Contractors differ in three ways:
duration, scope and review cadence.

## Onboarding

A contractor gets an Okta account scoped to a single project group, valid for the
contract end date plus seven days. There is no open-ended contractor account; an
extension is a new request, not an edit.

## What contractors never get

Contractors do not receive production database access, Vault write access, or
membership in any group that can approve a billing or authentication change.
A contractor may read production logs only through the redacted log view.

## Code access

Contractors are granted repository access per repository, never organisation
wide. Their pull requests always require two approvals regardless of what the
code review standard says for staff, and at least one approver must be a
full-time engineer on the owning team.

## Devices

Contractors using their own hardware work through a managed virtual desktop. No
customer data is permitted on an unmanaged device, and the virtual desktop
blocks clipboard egress and local file download.

## Review

Contractor access is reviewed monthly, not quarterly. A contractor with no
activity for 30 days is suspended automatically; reinstatement needs the
sponsoring manager's approval.

## Offboarding

Access is revoked on the contract end date by automation, not by a ticket. The
sponsoring manager gets a reminder seven days out and the revocation is logged
to the audit store, which is where any dispute about a date gets settled.
