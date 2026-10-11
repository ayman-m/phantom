# Exact upstream parsing and modeling rules: Okta, Proofpoint email, Google Workspace

Every file here is copied unchanged from [`demisto/content`](https://github.com/demisto/content)
at commit `8b3bcee4dcb24cda6fc9c605c7a2cbd1e30fb2a5` (master, 2026-09-29). Each rule keeps its
upstream directory layout: `<Pack>/<ModelingRules|ParsingRules>/<Rule>/` with the `.xif` rule,
its `.yml` descriptor and, for modeling rules, the `_schema.json` that declares the dataset columns.
`_manifest.json` lists every file with its size and how it compares with our local mirror.

## What each rule binds to

| Pack (version) | Parsing rule INGEST (vendor / product -> dataset) | Modeling rule datasets |
|---|---|---|
| `Okta` 3.4.6 | `okta`/`okta` -> `okta_okta_raw`; `okta`/`sso` -> `okta_sso_raw` (both: `_time = published`, `no_hit=keep`) | `okta_okta_raw` (`OktaModelingRules`, `_1_3`); `okta_okta_raw` + `okta_sso_raw` (`_2_0`, `_2_11`) |
| `ProofpointEmailSecurity` 1.0.29 | `proofpoint`/`email_security` -> `proofpoint_email_security_raw` | `proofpoint_email_security_raw` (base, `_2_11`) |
| `ProofpointTAP` 1.3.2 | `Proofpoint`/`Tap` -> `proofpoint_tap_raw` | `proofpoint_tap_raw` (`ProofpointTAPModelingRules`, `_1_3`) |
| `GoogleDrive` | `google_workspace`/`drive` -> `google_workspace_drive_raw` | `google_workspace_drive_raw` (`_1_3`, `_2_11`) |
| `GoogleChrome` | `Google`/`Workspace Chrome` or `Google`/`Workspace_Chrome` -> `google_workspace_chrome_raw` | `google_workspace_chrome_raw` (base, `_2_11`) |

## Things worth knowing

- **Google Workspace has no audit-log rules upstream.** The packs `GSuiteAdmin`, `GsuiteAuditor` and
  `GSuiteSecurityAlertCenter` ship no `ParsingRules` or `ModelingRules` at all (404 on both
  directories). The only rules under the Google Workspace name are Drive and Chrome, copied here.
- **Proofpoint has two different products.** `ProofpointEmailSecurity` (`proofpoint_email_security_raw`)
  is not `ProofpointTAP` (`proofpoint_tap_raw`).
- **The `okta_sso_raw` rule only exists in the 2.0 and 2.11 modeling rules.** It reads the System Log
  objects as top-level JSON columns (`actor`, `client`, `outcome`, `target`, `debugContext`,
  `securityContext`, `authenticationContext`, `transaction`, `request`, `eventType`, `uuid`, `published`).
- **`_2_11` variants are not in our local mirror** (`scripts/maintainer/modeling_rules/`): Okta,
  ProofpointEmailSecurity, GoogleDrive and GoogleChrome. Every rule the mirror does hold is
  byte-identical to upstream. The `Okta` `_2_11` file differs from `_2_0` by 33 lines.
- **Packs are not installed by copying these files.** They take effect only when the pack is installed
  in the tenant (Settings > Marketplace).

To refresh, re-run the fetch with a newer commit; nothing here is edited by hand.
