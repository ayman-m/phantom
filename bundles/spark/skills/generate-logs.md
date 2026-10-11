# Generate Logs

Use this skill when the operator asks Phantom to create synthetic
security telemetry.

Procedure:

1. Identify the target log source, format, volume, and **destination**
   (resolve the destination per the rule below — never hardcode one).
2. Call `phantom_get_technology_stack` when the operator does not
   provide a concrete schema.
3. Call `phantom_get_field_info` to confirm required parsed fields.
4. Call `phantom_generate_observables` when the workflow needs IPs,
   domains, hashes, URLs, users, hosts, or CVEs.
5. Call `phantom_create_data_worker` to start log generation, passing
   the resolved `destination` (a `logdest:<id>` reference — see below).
6. Return worker IDs, destination, format, rate, and any assumptions.

## Resolving the destination (no hardcoded destinations)

NEVER pass a hardcoded `udp:host:port` or `XSIAM_WEBHOOK` when a
configured log destination exists. Resolve against the operator's
configured Log Destinations every time:

1. **Determine the transport.** Use what the operator said ("send these
   over syslog", "to my XSIAM webhook"). If they didn't say, infer it
   from the data source's `how_to_use` / routing notes (e.g. a source
   documented as "simulated via syslog" implies a syslog destination).
2. **Call `log_destinations_list`** to see what's configured.
3. **Pick by the count that matches the transport:**
   - **Exactly one** matches → use it WITHOUT asking. Pass
     `destination="logdest:<id>"` using that destination's `id`.
   - **Two or more** match → if the operator already named one (by name,
     host, or IP), use that one; otherwise ASK which destination to use.
   - **None** match → offer to create one. For a plain **syslog** target
     you can create it directly with
     `log_destinations_create(name, host, port, protocol)` (secretless),
     then use its `id`. For a **credentialed** target (xsiam_http,
     webhook, splunk_hec) you CANNOT create it — guide the operator to
     add it on the `/log-destinations` page, then resume.
4. **Pass the reference.** Give `phantom_create_data_worker` the
   `destination="logdest:<id>"` reference. The platform resolves the
   concrete address — and, for an xsiam_http destination, injects the
   endpoint URL + auth key — server-side, before the worker is created.
   You never read, format, or handle a destination's credentials.

Raw `udp:host:port` is acceptable ONLY for an explicit, throwaway
one-shot the operator dictates and won't reuse. `webhook` and
`splunk_hec` destination types are not yet wired into log generation —
if the only matching destination is one of those, tell the operator and
ask for a syslog or xsiam_http destination instead.
