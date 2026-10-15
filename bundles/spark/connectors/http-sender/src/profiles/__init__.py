"""Built-in event profiles for `generate_events`.

A profile builds synthetic events for ONE data source. The transport does not care what an
event looks like (any JSON object is sent as given); a profile exists so the agent can ask
for a realistic scenario by name instead of authoring every field. Adding a source means
adding a module here and one line to PROFILES.

Each profile module provides:

  NAME              the value of generate_events(profile=...)
  DESCRIPTION       one line for the tool's error messages
  EXPECTED_DATASET  the collector the events are preferably sent to, e.g. "okta_okta"
  EXPECTED_DATASETS every collector they suit, preferred one first, e.g. ("okta_okta", "okta_sso"):
                    a destination outside this tuple is warned about, not refused
  SCENARIOS         tuple of scenario names
  TEST_ID_FIELD     field in sample_event() that carries a unique id, for the verify query
  TIME_FIELD        field that carries an event's time, reported as first_time/last_time
  build_events(scenario, count, *, view, now, spread_seconds, start_offset_minutes,
               target_user, source_ip, seed=None) -> list[dict]   (raises ValueError)
  sample_event(*, view, now) -> dict      one benign, identifiable event

`view` is the `runtime.organization_view.OrganizationView` the identities come from: the connector reads it at call time
(the active organization, or the one the instance's `organization` setting pins) and passes it in. A profile holds no
roster of its own: people, emails, ids, home addresses, cloud accounts, regions and the partner domain are the
organization's (see `_org.py`). It raises `OrganizationUnavailable` when the organization lacks something a scenario needs and
`_org.UnknownUser` (a ValueError) when `target_user` names nobody in it. Only the actors a recipe mints fresh (so a
first-time-seen detector fires) and the attacker's addresses (Tor exits, abroad ranges) are the profile's own.

and, for a profile whose events are meant for a Cribl destination (see ../cribl.py), optionally:

  CRIBL_DESTINATIONS  the `cribl_<source>` destinations that suit it, e.g. ("cribl_aws_audit",)
  DEFAULT_DESTINATION the destination `generate_events` uses when none is given (any scenario)
  SCENARIO_DESTINATION {scenario: destination} for the scenarios that default to a Cribl destination
  CRIBL_ONLY          True: with no destination given and none of CRIBL_DESTINATIONS configured, refuse rather than
                      fall back to the primary HTTP collector (a CloudTrail record must not land in an Okta dataset)
  MIN_COUNT           {scenario: fewest events that make its recipe complete}; build_events raises below it
  BENIGN_SCENARIOS    the scenarios that are baseline traffic (stable identities, no detector fires on them); the others
                      are attack recipes with fresh identities. Optional: a profile that has both kinds names its benign ones
  DEFAULT_COUNT       {scenario: events when the caller gives no `count`}; a scenario without an entry gets its MIN_COUNT for
                      a CRIBL_ONLY profile and 20 for the others
  WINDOWS_EVENTS      True for a profile whose events are STRUCTURED Windows events (`windows_events.prepare` renders them to
                      Event XML): they go only to the Windows destination, through `_deliver_windows`
  sample_id(event)    optional: the text `generate_events` reports as an event's sample id, for a profile whose events have no
                      id field (TEST_ID_FIELD is used otherwise)
  describe(events)    optional: a dict merged into the `generate_events` result (the windows profile names the accounts that acted)
"""
from __future__ import annotations

from types import ModuleType

from . import aws_cloudtrail, azure_ad_audit, gcp_audit, google_workspace, okta, proofpoint_tap, windows

PROFILES: dict[str, ModuleType] = {
    m.NAME: m for m in (okta, proofpoint_tap, google_workspace, aws_cloudtrail, gcp_audit, azure_ad_audit, windows)}


def get(name: str) -> ModuleType:
    """The profile called `name` (case-insensitive). Raises ValueError listing the choices."""
    profile = PROFILES.get((name or "").strip().lower())
    if profile is None:
        raise ValueError(f"unknown profile {name!r}; choose one of {', '.join(sorted(PROFILES))}")
    return profile


def default_destination(profile: ModuleType, scenario: str) -> str | None:
    """The destination `scenario` of `profile` uses when the caller names none, or None for the primary one."""
    return getattr(profile, "SCENARIO_DESTINATION", {}).get(scenario) or getattr(profile, "DEFAULT_DESTINATION", None)


def for_destination(destination: str) -> ModuleType | None:
    """The profile that is meant for the Cribl destination called `destination`, if any."""
    return next((p for p in PROFILES.values() if destination in getattr(p, "CRIBL_DESTINATIONS", ())), None)
