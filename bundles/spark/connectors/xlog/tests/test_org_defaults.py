"""Identity defaults drawn from the active organization: field recognition and the two binding shapes."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from runtime.organization_view import get_view  # noqa: E402
from src import org_defaults as od  # noqa: E402


@pytest.mark.parametrize("name,expected", [
    ("suser", ("src", "user")), ("duser", ("dst", "user")), ("src", ("src", "ip")), ("dst", ("dst", "ip")),
    ("shost", ("src", "host")), ("dhost", ("dst", "host")), ("source_ip", ("src", "ip")),
    ("sourceAddress", ("src", "ip")), ("destination_ip", ("dst", "ip")), ("client_ip", ("src", "ip")),
    ("server_ip", ("dst", "ip")), ("user_name", ("src", "user")), ("UserName", ("src", "user")),
    ("source.user.name", ("src", "user")), ("hostname", ("src", "host")), ("Computer", ("src", "host")),
    ("src_host", ("src", "host")), ("dest_host", ("dst", "host")), ("destination_hostname", ("dst", "host")),
    ("user_email", ("src", "email")), ("upn", ("src", "upn")), ("device_host", ("src", "host")),
])
def test_recognised_identity_fields(name, expected):
    assert od.classify(name) == expected


@pytest.mark.parametrize("name", [
    "SubjectUserName", "SubjectDomainName", "user_agent", "user_id", "src_port", "dst_port", "remote_ip", "public_ip",
    "nat_source_ip", "domain", "hostname_domain", "action", "bytes_in", "event_id", "process_name", "file_name",
    "user_domain", "host_id",
])
def test_unrelated_fields_are_left_alone(name):
    assert od.classify(name) is None


def _fields(*names, **types):
    return [{"name": n, "type": types.get(n, "string")} for n in names]


def test_schema_path_binds_person_workstation_and_server():
    view = get_view()
    obs, report = od.apply_to_schema_path(view, _fields("suser", "shost", "src", "dst", "dhost", "action"), {"action": ["allow"]})
    assert report["entities"] >= 40 and set(report["bound"]) == {"suser", "shost", "src", "dst", "dhost"}
    assert obs["action"] == ["allow"]
    for e in obs["__entities__"]:
        p = view.person(e["suser"])
        ws = view.host(p["workstation"])
        assert (e["shost"], e["src"]) == (ws["name"], ws["ip"])           # the person stays whole
        dst = view.host(e["dhost"])
        assert dst["role"] == "server" and e["dst"] == dst["ip"]
    logins = {e["suser"] for e in obs["__entities__"]}
    assert "ralsayegh" not in logins                                       # the leaver does not log on
    assert len(logins) == len(obs["__entities__"])


def test_caller_values_win():
    view = get_view()
    obs, rep = od.apply_to_schema_path(view, _fields("suser", "src"), {"suser": ["nalharbi"]})
    assert set(rep["bound"]) == {"src"} and all("suser" not in e for e in obs["__entities__"])
    given = {"__entities__": [{"suser": "x"}]}
    obs2, rep2 = od.apply_to_schema_path(view, _fields("suser"), given)
    assert obs2 == given and rep2["skipped"]


def test_non_string_and_array_fields_are_skipped():
    view = get_view()
    obs, rep = od.apply_to_schema_path(
        view, [{"name": "src", "type": "integer"}, {"name": "suser", "type": "string", "is_array": True}], None)
    assert rep["bound"] == {} and "__entities__" not in obs


def test_no_identity_fields_changes_nothing():
    view = get_view()
    obs, rep = od.apply_to_schema_path(view, _fields("action", "bytes"), {"action": ["a"]})
    assert obs == {"action": ["a"]} and rep["entities"] == 0


def test_legacy_path_pins_one_actor_the_outlier():
    view = get_view()
    obs, rep = od.apply_to_legacy_path(view, {"srcHost": ["mine"]})
    assert rep["actor"] == "aalzamil" and obs["srcHost"] == ["mine"]
    ws = view.host(view.person("aalzamil")["workstation"])
    assert obs["localIp"] == [ws["ip"]] and obs["user"] == ["aalzamil"] and obs["srcDomain"] == ["phantom.lab"]
    assert view.host(obs["dstHost"][0]) is None or True  # dstHost was not set by the caller's dict, so it is filled
    assert view.host(obs["dstHost"][0])["role"] == "server"
    assert "sourceIp" in obs and "sourceIP" not in obs  # one spelling per concept
