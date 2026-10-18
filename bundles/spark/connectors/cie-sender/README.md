# cie-sender

Provisions a synthetic directory into a Palo Alto Networks **Cloud Identity Engine** (CIE) **SCIM directory**, so Cortex
XSIAM receives directory context (the `pan_dss_raw` dataset). Cortex requires a paired CIE before its Identity Analytics
detectors are active.

CIE accepts directories over SCIM 2.0. This connector is the SCIM client: it creates, updates and removes users and
groups the way an identity provider's provisioning service does. No directory server, Cloud Identity Agent or Windows
host is needed.

## What it provisions

The active organization (the Organization page): the people, separate `adm.` administrator accounts, service accounts and
break-glass account that every Phantom tool already generates logs for, with the same names and logins. A leaver is
provisioned disabled. It adds:

- **Departments, titles and managers:** as the organization defines them (the manager chain is the organization's).
- **Groups:** the organization's groups (a group per department, `SG-VPN-Users`, `SG-Project-Atlas`, `SG-Contractors`,
  `SG-Service-Accounts`, and the privileged `SG-IT-Admins` and `Domain Admins`), with the members its people list.
- **userName format:** `nalharbi@phantom.lab` by default (`userNameStyle: sam`, the login Windows events carry), or
  `noura.alharbi@phantom.lab` (`dotted`, the form the Okta and cloud profiles use). The email is always the dotted form.

Every object it creates has an `externalId` starting `phantom:`. The connector never changes or deletes anything else.
If the SCIM server does not keep `externalId`, an object without one counts as Phantom's only when its userName or
group name is one this directory provisions.

## Setting it up

You do the CIE and XSIAM steps yourself, because both are behind your own login.

1. **Pair CIE with XSIAM.**
   - Activate CIE in the same region as the tenant.
   - In XSIAM, go to Settings > Configuration > Integrations > Cloud Identity Engine, select the instance and save.
   - Without this pairing nothing reaches `pan_dss_raw`, however the directory is fed.
2. **Create the SCIM directory.** In the CIE app:
   1. Go to Directory Sync > Directories > Add New Directory > Cloud Directory > Set Up > SCIM.
   2. Choose client **Others**.
   3. Enter a Directory ID (up to 40 letters, digits or hyphens, for example `phantom-scim`) and a Directory Name (for
      example `phantom.lab`).
   4. Copy the **Base URL**.
   5. Choose **Static Bearer Token** and click **Generate Token**. Copy the token: it is shown once.
   6. Click **Submit**.
3. **Create the Phantom instance.** In Phantom, open Connectors > cie-sender > Create instance:
   - put the Base URL in `scimBaseUrl`;
   - put the token in the `scimToken` secret;
   - leave `organization` empty to follow the active organization (or enter an organization id to pin the instance to one).
4. **Provision.** Ask the agent to run `test_connection`, then `provision_directory`. `provision_directory` with
   `dry_run: true` shows what it will create.
5. **Run a full sync.** In the CIE app, run Actions > **Full Sync** on the directory. CIE setup is not complete until a
   full sync succeeds, and the directory's SCIM Change Timestamp should now be filled in.
6. **Verify in XSIAM** with `dataset = pan_dss_raw | limit 10`. The users should appear in a few minutes.

If CIE shows the users but `pan_dss_raw` stays empty, check the pairing (step 1) first. If the pairing is in place,
create the SCIM directory again with client **Entra ID** instead of Others. The XSIAM documentation names on-premises
Active Directory and Microsoft Entra ID as the supported directories, so the client type may matter.

## Tools

| Tool | What it does |
|---|---|
| `test_connection` | Runs one filtered `GET /Users` and changes nothing. |
| `provision_directory` | Creates or updates the directory. Safe to repeat. `dry_run` previews it. To add people, edit the organization and run it again. |
| `list_directory` | Returns one page of users or groups, as summaries. |
| `update_user` | Changes a user's title, department, display name or manager, or disables the account (`active: false`). |
| `set_group_membership` | Adds a user to a group or removes them, for example adding someone to `Domain Admins`. |
| `remove_provisioned` | **Destructive.** Deletes everything the connector created. It needs `confirm: true`. Without it, the tool only counts. |

The token lives only in the instance's secret slot and is sent only as the `Authorization: Bearer` header. No tool
accepts it or returns it.

## Development

```bash
python3 -m pytest -x        # from this directory; the SCIM server is an in-memory fake
docker build -f bundles/spark/connectors/cie-sender/Dockerfile -t ghcr.io/ayman-m/phantom-connector-cie-sender-oss:0.1.0 .   # from the repo root
```
