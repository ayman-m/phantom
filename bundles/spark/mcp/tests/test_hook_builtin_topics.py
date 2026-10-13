"""The topics the agent's built-in hooks publish must be declared in the manifest.

NotificationStore.publish() raises ValueError for any topic missing from
bundles/spark/manifest.yaml `notifications.topics`, which the API turns into a
400. The built-in hooks (mcp/agent/lib/hook-builtins/) publish with a fixed
topic constant, so a constant that drifts from the manifest silently drops
every notification: the hook fires and the audit row exists, but the operator
sees nothing.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

from src.usecase.notifications import SqliteNotificationStore, TopicSpec

REPO = Path(__file__).resolve().parents[4]
MANIFEST = REPO / "bundles" / "spark" / "manifest.yaml"
TOPICS_TS = REPO / "mcp" / "agent" / "lib" / "hook-builtins" / "notification-topics.ts"

# Pinned so renaming a topic is a deliberate act that updates the journey, the
# docs and this test together.
EXPECTED = {"cost-warning", "context-warning"}


def _manifest_topics() -> list[dict]:
    return yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))["notifications"]["topics"]


def _ts_topics() -> set[str]:
    if not TOPICS_TS.exists():
        pytest.skip("agent source tree not present")
    src = TOPICS_TS.read_text(encoding="utf-8")
    return set(re.findall(r'export const \w+_TOPIC = "([^"]+)";', src))


def test_the_agent_topic_constants_are_the_two_expected_names() -> None:
    assert _ts_topics() == EXPECTED


def test_every_hook_topic_is_declared_in_the_manifest() -> None:
    declared = {t["name"]: t for t in _manifest_topics()}
    for topic in _ts_topics() | EXPECTED:
        assert topic in declared, f"{topic} is not declared in manifest notifications.topics"
        assert declared[topic]["severity"] == "warning"
        assert declared[topic]["target"] == "user:operator"


def test_the_store_built_from_the_manifest_accepts_the_hook_topics(tmp_path) -> None:
    store = SqliteNotificationStore(
        topics=[TopicSpec.from_manifest(t) for t in _manifest_topics()],
        data_root=tmp_path,
    )
    for topic in sorted(EXPECTED):
        n = store.publish(topic, payload={"title": "t", "body": "b"})
        assert n.topic == topic
        assert n.severity == "warning"
