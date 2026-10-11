"""A source's field rows are written once, at install time.

That is the whole reason this backfill exists. `ALTER TABLE ... ADD COLUMN ... DEFAULT ''`
creates the column but not the data, and nothing else ever rewrites those rows — so a source
installed before a column was added keeps an empty value for it forever, while the bundled YAML
on the same disk has the answer.

Without the backfill an installed source could carry descriptions but no examples, and report
`is_gate=False` regardless of its YAML — and the gate field is the one an operator most needs to
see, since seeding it wrong means XDM stays empty with no error.
"""
import sqlite3

import pytest

from usecase.data_sources_store import DataSource, DataSourceField, DataSourcesStore

DS_ID = "MicrosoftWindowsEvents/MicrosoftWindowsEvents/microsoft_windows_raw"
# Three of these are gates in the bundled YAML; the rest are ordinary columns.
FIELD_NAMES = ("channel", "provider_name", "time_created", "message", "event_result", "record_id")


def _store_with_stale_install(tmp_path):
    """A store holding one source whose field metadata is empty — a pre-migration install."""
    db = tmp_path / "data_sources.db"
    store = DataSourcesStore(db_path=db)
    store.install(
        DataSource(
            id=DS_ID,
            pack_name="MicrosoftWindowsEvents",
            rule_name="MicrosoftWindowsEvents",
            dataset_name="microsoft_windows_raw",
            installed_at="2026-01-01T00:00:00Z",
        ),
        [DataSourceField(name=n, type="string") for n in FIELD_NAMES],
        [],
    )
    con = sqlite3.connect(db)
    con.execute("UPDATE data_source_fields SET example='', is_gate=0, description=''")
    con.commit()
    return store, con


def test_backfill_populates_example_and_gate_from_bundled_yaml(tmp_path):
    store, con = _store_with_stale_install(tmp_path)

    def count(where):
        return con.execute(f"select count(*) from data_source_fields where {where}").fetchone()[0]

    assert count("example != ''") == 0, "fixture should start with no examples"
    assert count("is_gate = 1") == 0

    stats = store.backfill_field_metadata_from_yaml()

    assert count("example != ''") == len(FIELD_NAMES), (
        "every field in the bundled YAML carries an example, so every row should be filled"
    )
    # channel / provider_name / time_created are the three gates on this source. Their values
    # are load-bearing: provider_name is the ONLY route a Security-channel event has past the
    # modeling gate, and time_created is a hard no_hit=drop parsing gate.
    gates = {r[0] for r in con.execute("select field_name from data_source_fields where is_gate=1")}
    assert gates == {"channel", "provider_name", "time_created"}, gates
    assert stats["example"] == len(FIELD_NAMES)
    assert stats["sources"] >= 1


def test_backfill_is_idempotent(tmp_path):
    """Runs on every boot, so a second pass must be a no-op rather than churning rows."""
    store, _ = _store_with_stale_install(tmp_path)
    store.backfill_field_metadata_from_yaml()
    second = store.backfill_field_metadata_from_yaml()
    assert second["example"] == 0
    assert second["is_gate"] == 0
    assert second["description"] == 0
    assert second["enum_values"] == 0


def test_backfill_never_clobbers_an_operator_edit(tmp_path):
    """Only EMPTY cells are filled. An operator who edited a value keeps it."""
    store, con = _store_with_stale_install(tmp_path)
    con.execute(
        "UPDATE data_source_fields SET example = ? WHERE field_name = 'channel'",
        ("operator-chosen-value",),
    )
    con.commit()

    store.backfill_field_metadata_from_yaml()

    kept = con.execute(
        "select example from data_source_fields where field_name = 'channel'"
    ).fetchone()[0]
    assert kept == "operator-chosen-value"
    # ...while a genuinely empty sibling still gets filled.
    filled = con.execute(
        "select example from data_source_fields where field_name = 'provider_name'"
    ).fetchone()[0]
    assert filled and filled != ""


def test_installed_field_roundtrips_is_gate(tmp_path):
    """The INSERT must persist is_gate, so a FRESH install keeps it too."""
    db = tmp_path / "data_sources.db"
    store = DataSourcesStore(db_path=db)
    store.install(
        DataSource(
            id=DS_ID,
            pack_name="MicrosoftWindowsEvents",
            rule_name="MicrosoftWindowsEvents",
            dataset_name="microsoft_windows_raw",
            installed_at="2026-01-01T00:00:00Z",
        ),
        [
            DataSourceField(name="provider_name", type="string", is_gate=True, example="X"),
            DataSourceField(name="message", type="string", is_gate=False, example="Y"),
        ],
        [],
    )
    expanded = store.get_with_schema(DS_ID)
    assert expanded is not None
    by_name = {f.name: f for f in expanded.fields}
    assert by_name["provider_name"].is_gate is True
    assert by_name["message"].is_gate is False


@pytest.mark.parametrize("column", ["example", "is_gate"])
def test_migration_adds_the_column_to_a_pre_existing_table(tmp_path, column):
    """The PRAGMA-guarded ALTER must be able to upgrade a table created without the column."""
    db = tmp_path / "data_sources.db"
    DataSourcesStore(db_path=db)          # build the full, current schema first

    # Now rewind data_source_fields to its pre-migration shape, so the next
    # constructor call has to migrate a real legacy table rather than a stub.
    con = sqlite3.connect(db)
    con.executescript(
        """
        DROP TABLE data_source_fields;
        CREATE TABLE data_source_fields (
            data_source_id TEXT NOT NULL,
            field_name     TEXT NOT NULL,
            field_type     TEXT,
            is_array       INTEGER NOT NULL DEFAULT 0,
            is_meta        INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (data_source_id, field_name)
        );
        """
    )
    con.commit()
    con.close()

    DataSourcesStore(db_path=db)          # constructor runs the migrations

    con = sqlite3.connect(db)
    cols = {r[1] for r in con.execute("PRAGMA table_info(data_source_fields)")}
    assert column in cols
