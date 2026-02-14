"""Tests for gralph.tasks.validate — schema validation + cycle detection."""

from __future__ import annotations

import json
from pathlib import Path


from gralph.io_utils import write_text
from gralph.tasks.model import Task, TaskFile
from gralph.tasks.validate import detect_cycles, validate, load_mutex_catalog


# ── Helpers ─────────────────────────────────────────────────────────


def _t(
    id: str,
    title: str = "",
    depends_on: list[str] | None = None,
    mutex: list[str] | None = None,
) -> Task:
    return Task(
        id=id,
        title=title or f"Task {id}",
        depends_on=depends_on or [],
        mutex=mutex or [],
    )


def _tf(tasks: list[Task]) -> TaskFile:
    return TaskFile(branch_name="test", tasks=tasks)


# ═══════════════════════════════════════════════════════════════════
#  Cycle Detection
# ═══════════════════════════════════════════════════════════════════


class TestDetectCycles:
    """Tests for detect_cycles()."""

    def test_no_cycles_simple_chain(self):
        """A -> B -> C has no cycle."""
        tf = _tf([
            _t("A"),
            _t("B", depends_on=["A"]),
            _t("C", depends_on=["B"]),
        ])
        assert detect_cycles(tf) == ""

    def test_no_cycles_independent_tasks(self):
        """Tasks with no dependencies have no cycles."""
        tf = _tf([_t("A"), _t("B"), _t("C")])
        assert detect_cycles(tf) == ""

    def test_direct_cycle(self):
        """A -> B -> A is a cycle."""
        tf = _tf([
            _t("A", depends_on=["B"]),
            _t("B", depends_on=["A"]),
        ])
        result = detect_cycles(tf)
        assert result != ""
        assert "A" in result
        assert "B" in result

    def test_self_cycle(self):
        """A -> A is a cycle."""
        tf = _tf([_t("A", depends_on=["A"])])
        result = detect_cycles(tf)
        assert result != ""
        assert "A" in result

    def test_indirect_cycle(self):
        """A -> B -> C -> A is a cycle."""
        tf = _tf([
            _t("A", depends_on=["C"]),
            _t("B", depends_on=["A"]),
            _t("C", depends_on=["B"]),
        ])
        result = detect_cycles(tf)
        assert result != ""

    def test_diamond_no_cycle(self):
        """Diamond shape (A -> B, A -> C, B -> D, C -> D) has no cycle."""
        tf = _tf([
            _t("A"),
            _t("B", depends_on=["A"]),
            _t("C", depends_on=["A"]),
            _t("D", depends_on=["B", "C"]),
        ])
        assert detect_cycles(tf) == ""

    def test_empty_tasks(self):
        """No tasks means no cycles."""
        tf = _tf([])
        assert detect_cycles(tf) == ""


# ═══════════════════════════════════════════════════════════════════
#  Schema Validation
# ═══════════════════════════════════════════════════════════════════


class TestValidate:
    """Tests for validate()."""

    def test_valid_simple(self):
        """Valid task file produces no errors."""
        tf = _tf([
            _t("TASK-001", "Setup project"),
            _t("TASK-002", "Add auth", depends_on=["TASK-001"]),
        ])
        errors = validate(tf)
        assert errors == []

    def test_empty_tasks(self):
        """Empty task list is an error."""
        tf = _tf([])
        errors = validate(tf)
        assert any("No tasks" in e for e in errors)

    def test_duplicate_ids(self):
        """Duplicate IDs are detected."""
        tf = _tf([
            _t("TASK-001", "First"),
            _t("TASK-001", "Duplicate"),
        ])
        errors = validate(tf)
        assert any("Duplicate id" in e for e in errors)

    def test_missing_id(self):
        """Task with empty ID is an error."""
        tf = _tf([Task(id="", title="No ID")])
        errors = validate(tf)
        assert any("missing id" in e for e in errors)

    def test_missing_title(self):
        """Task with empty title is an error."""
        tf = _tf([Task(id="TASK-001", title="")])
        errors = validate(tf)
        assert any("missing title" in e for e in errors)

    def test_invalid_dependency_reference(self):
        """Dependency referencing non-existent task is an error."""
        tf = _tf([
            _t("TASK-001", depends_on=["NONEXISTENT"]),
        ])
        errors = validate(tf)
        assert any("not found" in e for e in errors)

    def test_invalid_version(self):
        """Version other than 0 or 1 is an error."""
        tf = TaskFile(branch_name="test", version=99, tasks=[_t("A")])
        errors = validate(tf)
        assert any("version" in e for e in errors)

    def test_valid_versions(self):
        """Version 0 and 1 are both valid."""
        tf0 = TaskFile(branch_name="test", version=0, tasks=[_t("A")])
        tf1 = TaskFile(branch_name="test", version=1, tasks=[_t("A")])
        assert validate(tf0) == []
        assert validate(tf1) == []

    def test_contract_mutex_always_valid(self):
        """Mutex starting with 'contract:' is always valid, even without catalog."""
        tf = _tf([_t("A", mutex=["contract:auth-api"])])
        errors = validate(tf)
        assert errors == []

    def test_cycle_reported_in_validate(self):
        """Cycles are included in validate() output."""
        tf = _tf([
            _t("A", depends_on=["B"]),
            _t("B", depends_on=["A"]),
        ])
        errors = validate(tf)
        assert any("Cycle" in e for e in errors)


# ═══════════════════════════════════════════════════════════════════
#  Mutex Catalog
# ═══════════════════════════════════════════════════════════════════


class TestMutexCatalog:
    """Tests for mutex catalog validation."""

    def test_load_mutex_catalog(self, tmp_path: Path):
        """Load mutex catalog from JSON file."""
        catalog_data = {
            "mutex": {
                "db-migrations": {"description": "DB migrations"},
                "lockfile": {"description": "Lock file"},
            }
        }
        catalog_file = tmp_path / "mutex-catalog.json"
        write_text(catalog_file, json.dumps(catalog_data))

        result = load_mutex_catalog(tmp_path)
        assert result is not None
        assert "db-migrations" in result
        assert "lockfile" in result

    def test_load_mutex_catalog_missing_falls_back_to_bundled(self, tmp_path: Path):
        """Missing catalog in base_dir falls back to bundled catalog."""
        result = load_mutex_catalog(tmp_path)
        # Bundled catalog provides defaults
        assert result is not None
        assert "db-migrations" in result

    def test_load_mutex_catalog_none_base_dir(self):
        """None base_dir still loads bundled catalog."""
        result = load_mutex_catalog(None)
        assert result is not None

    def test_unknown_mutex_with_catalog(self, tmp_path: Path):
        """Unknown mutex is flagged when catalog exists."""
        catalog_data = {"mutex": {"db-migrations": {}}}
        catalog_file = tmp_path / "mutex-catalog.json"
        write_text(catalog_file, json.dumps(catalog_data))

        tf = _tf([_t("A", mutex=["unknown-mutex"])])
        errors = validate(tf, base_dir=tmp_path)
        assert any("unknown mutex" in e for e in errors)

    def test_known_mutex_with_catalog(self, tmp_path: Path):
        """Known mutex passes validation when catalog exists."""
        catalog_data = {"mutex": {"db-migrations": {}}}
        catalog_file = tmp_path / "mutex-catalog.json"
        write_text(catalog_file, json.dumps(catalog_data))

        tf = _tf([_t("A", mutex=["db-migrations"])])
        errors = validate(tf, base_dir=tmp_path)
        assert errors == []

    def test_contract_mutex_valid_with_catalog(self, tmp_path: Path):
        """Contract mutexes are valid even when not in catalog."""
        catalog_data = {"mutex": {"db-migrations": {}}}
        catalog_file = tmp_path / "mutex-catalog.json"
        write_text(catalog_file, json.dumps(catalog_data))

        tf = _tf([_t("A", mutex=["contract:auth-api"])])
        errors = validate(tf, base_dir=tmp_path)
        assert errors == []
