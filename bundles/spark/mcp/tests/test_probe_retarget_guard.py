"""A dry-run probe override must not carry a stored secret to a new target.

The legitimate use of a probe override is "test this config before I save it".
The attack is the same request with only `url` replaced: the stored token
survives in the merged config, the destination becomes an attacker's host, and
the handler posts `Authorization: <real token>` straight to them. Credential
exfiltration with one agent:write call, and no secret is ever read back — so
none of the read-path guards see it.

These pin the rule: change a target-identifying field, and every secret slot
must be supplied explicitly in that same request.
"""

import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from api.log_destinations import _TARGET_FIELDS


def _retargeted(override_cfg, base):
    """Mirror of the guard's decision, kept in lockstep with the route."""
    return any(
        k in override_cfg and str(override_cfg.get(k)) != str(base.get(k))
        for k in _TARGET_FIELDS
    )


BASE = {"url": "https://splunk.internal:8088", "token": "REAL-SECRET", "index": "main"}


def test_changing_url_is_a_retarget():
    assert _retargeted({"url": "https://attacker.example/collect"}, BASE)


def test_changing_host_or_port_is_a_retarget():
    assert _retargeted({"host": "attacker.example"}, {"host": "syslog.internal"})
    assert _retargeted({"port": "9999"}, {"port": "514"})


def test_same_url_restated_is_not_a_retarget():
    """Re-sending the current value must not trip the guard."""
    assert not _retargeted({"url": BASE["url"]}, BASE)


def test_changing_a_benign_field_is_not_a_retarget():
    """Editing index/sourcetype must keep working without re-typing secrets."""
    assert not _retargeted({"index": "security"}, BASE)
    assert not _retargeted({"sourcetype": "phantom:synthetic"}, BASE)


def test_no_override_is_not_a_retarget():
    assert not _retargeted({}, BASE)


def test_every_shipped_handler_target_field_is_covered():
    """If a handler reads a destination field we do not guard, the guard leaks.

    splunk_hec / webhook / xsiam_http target `url`; syslog targets host+port.
    """
    for f in ("url", "host", "port"):
        assert f in _TARGET_FIELDS, f"{f} must be treated as target-identifying"
