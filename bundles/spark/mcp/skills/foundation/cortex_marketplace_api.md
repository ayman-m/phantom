---
name: cortex_marketplace_api
displayName: Cortex XSIAM Marketplace content-pack API (list, inspect, install)
category: foundation
description: 'Drive the Cortex XSIAM content-pack Marketplace over the tenant REST API — list installed packs, read pack metadata, and install or upgrade packs without the UI. Use when the operator asks to install/upgrade a Marketplace pack, enable a new data source''s parsing/modeling rules on the tenant, or audit which packs and versions are installed. Documents the exact endpoints, the install request shape, the circular-dependency workaround (batch the closure in ONE call), the opaque 101704 install failure (a tenant parsing-rule validator or a failing mandatory dependency, not a version problem), and how installs and deletes behave.'
icon: api
source: platform
loadingMode: on-demand
locked: false
---

# Skill: Cortex Marketplace content-pack API

## When this skill applies

- *"Install the Okta / Office365 / <vendor> pack on the tenant."*
- *"Which packs are installed, and at what versions?"*
- *"We're about to simulate vendor X — is its parsing/modeling pack installed?"* (If the pack is
  not installed, modeling rules do not apply and the events land raw-only.)

All calls go to the **tenant API URL** (e.g. `https://api-<tenant>.xdr.<region>.paloaltonetworks.com`)
with a standard API key:

```
Authorization: <API key>
x-xdr-auth-id: <API key ID>
Content-Type: application/json
```

## Endpoints

| Call | Purpose |
|---|---|
| `GET /xsoar/contentpacks/marketplace/<packId>` | Pack metadata: latest version (a `?version=` parameter is ignored), dependencies with a `mandatory` flag, content items |
| `GET /xsoar/contentpacks/metadata/installed` | The installed packs with their versions |
| `POST /xsoar/contentpacks/marketplace/install` | Install or upgrade packs. Body: `{"packs":[{"id":"<packId>","version":"<version>"}]}` |
| `POST /xsoar/contentpacks/installed/delete` | Delete packs. Body: `{"IDs":["<packId>"]}`; returns `{}` at once and the removal lands 30-60 s later (poll the installed list) |

The install response returns the **full installed-pack list** after the operation — use it as
the verification step. An install can run past a minute, so a client timeout is not a failure:
poll the installed list and do not re-post. **Installs are atomic**: a batch with one failing
pack installs nothing, so bisect by installing one pack per call.

## Circular dependencies: batch the closure in ONE call

Packs like `Base` ↔ `Core` depend on each other, so installing one alone fails with a dependency
error. Resolve the full dependency closure first (walk each pack's `dependencies` from the
metadata endpoint), then put **all of them in a single install call**. Working example:

```json
{"packs": [
  {"id": "Base",          "version": "1.42.27"},
  {"id": "Core",          "version": "3.5.91"},
  {"id": "CommonScripts", "version": "1.22.57"},
  {"id": "rasterize",     "version": "2.1.46"}
]}
```

## Known failure: `101704 Installation has failed`

The API returns only this opaque id, with no reason. It is not a dependency-version or
package-version problem:

- **The tenant's parsing-rule validator rejects the pack.** `AzureKubernetesServices`,
  `AzureFlowLogs` and `AzureAppService` can fail with 101704 even installed **alone**, while
  `AzureFirewall`, `AzureWAF`, `GoogleCloudLogging` and `AWS-CloudTrail` install fine. An
  *installed* AKS pack can make the Parsing Rules editor refuse every save and make the `Okta` and
  `Office365` installs fail with 101704; deleting that one pack fixes Okta. The Cortex UI runs the
  same validation but shows the message.
- **A failing mandatory dependency blocks the pack that needs it.** `dependencies[*].mandatory` in
  the metadata decides it: `MicrosoftEntraID` needs AKS, AzureFlowLogs and AzureAppService, and
  answers "required dependencies are missing" when they are not installed. Install the closure in
  one call, or one pack at a time, dependencies first.
- **Deleting a pack removes the packs that depend on it** (deleting AKS removed Entra). Datasets and
  their rows survive a pack delete.

What to do: bisect (one pack per install call), delete the offending pack, install what you need
first and the offending pack last or not at all, and tell the operator, who can try the UI to read
the validator message. Never author custom parsing or modeling rules as a workaround unless the
operator asks for it.

## Which pack carries the rules

A vendor's parsing and modeling rules ship in the vendor's own pack, whatever path the data takes.
The Cribl integration has **no Cortex-side rules pack**: the marketplace `Cribl` pack is a Cribl
Search action integration. Events sent with a source's dedicated Cribl UUID use the vendor pack
(`AWS-CloudTrail` for `amazon_aws_raw`, `GoogleCloudLogging` for `google_cloud_logging_raw`,
`MicrosoftEntraID` for the two Azure AD datasets, `Okta` for `okta_sso_raw`). `datamodel`
applies at query time, so rows that landed before the pack was installed gain their `xdm.*` fields
immediately after it.

## Workflow

1. `GET` the pack metadata → note the latest `version` and the `dependencies` map.
2. Build the closure (the pack + every transitive dependency at a compatible version).
3. `POST` the whole closure in one install call.
4. Verify from the response's installed list (or re-`GET` the pack).
5. On `101704`, bisect and tell the operator (see the section above); do not assume the UI will succeed.

## Why packs matter for simulation

A vendor's **parsing and modeling rules ship in its content pack**. Sending perfectly-shaped CEF
for a vendor whose pack is not installed lands events in the derived `<vendor>_<product>_raw`
dataset with **zero XDM mapping** — invisible to analytics detectors. Before crafting a new
vendor's telemetry, confirm the pack is installed (this API) or install it (this API, or the UI
for the 101704 cases). Exception: PAN-OS NGFW is parsed **natively** by the platform — no pack
needed for `panw_ngfw_*_raw`.
