import importlib.util
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect


def _load_migration(name: str):
    path = Path(__file__).parents[1] / "alembic" / "versions" / name
    spec = importlib.util.spec_from_file_location(name.removesuffix(".py"), path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run_revision(connection, revision, operation: str) -> None:
    context = MigrationContext.configure(connection)
    with Operations.context(context):
        getattr(revision, operation)()


@pytest.mark.parametrize(
    "table_name",
    [
        "accounts",
        "access_tokens",
        "problem_submission_permissions",
        "submissions",
        "evaluations",
    ],
)
def test_stage_d_migration_creates_required_tables(tmp_path, table_name: str) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'stage-d.db'}")
    revision_0001 = _load_migration("0001_create_problems_table.py")
    revision_0002 = _load_migration("0002_create_evaluation_runs_table.py")
    revision_0003 = _load_migration("0003_create_accounts_submissions_evaluations.py")

    with engine.begin() as connection:
        _run_revision(connection, revision_0001, "upgrade")
        _run_revision(connection, revision_0002, "upgrade")
        _run_revision(connection, revision_0003, "upgrade")
        assert table_name in inspect(connection).get_table_names()

        _run_revision(connection, revision_0003, "downgrade")
        assert table_name not in inspect(connection).get_table_names()

    engine.dispose()