"""PostgreSQL tests for explicit memory lifecycle and evidence provenance."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from uuid import uuid4

import pytest

DATABASE_URL = os.getenv("PERSONAL_AI_BRAIN_TEST_DATABASE_URL")
if not DATABASE_URL:
    pytest.skip("PostgreSQL test database URL is not configured", allow_module_level=True)

psycopg = pytest.importorskip("psycopg")
from psycopg import sql  # noqa: E402
from psycopg.errors import RaiseException  # noqa: E402

from personal_ai_brain.memory.models import (  # noqa: E402
    InvalidMemoryTransition,
    MemoryDraft,
    MemoryEvidence,
    MemoryOrigin,
    MemoryState,
)
from personal_ai_brain.memory.repository import PostgresMemoryRepository  # noqa: E402

MIGRATIONS = [
    Path(__file__).parents[2] / "infrastructure/postgres/migrations/0001_asset_registry.sql",
    Path(__file__).parents[2] / "infrastructure/postgres/migrations/0005_memory_lifecycle.sql",
]


@pytest.fixture
def memory_environment():
    connection = psycopg.connect(DATABASE_URL)
    schema_name = f"brain_memory_test_{uuid4().hex}"
    try:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema_name)))
        connection.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(schema_name)))
        for migration in MIGRATIONS:
            connection.execute(migration.read_text(encoding="utf-8"))
        connection.commit()

        def connect():
            return psycopg.connect(DATABASE_URL, options=f"-c search_path={schema_name}")

        root_id, asset_id, version_id = uuid4(), uuid4(), uuid4()
        connection.execute(
            """
            INSERT INTO storage_roots (id, display_name, uri, kind)
            VALUES (%s, 'Memory test', 'file:///tmp/memory-test', 'local')
            """,
            (root_id,),
        )
        connection.execute("INSERT INTO assets (id) VALUES (%s)", (asset_id,))
        connection.execute(
            "INSERT INTO asset_versions (id, asset_id, sha256, size_bytes) VALUES (%s, %s, %s, 4)",
            (version_id, asset_id, hashlib.sha256(b"test").hexdigest()),
        )
        connection.commit()
        yield PostgresMemoryRepository(connect), connection, str(version_id)
    finally:
        connection.rollback()
        connection.close()
        with psycopg.connect(DATABASE_URL) as cleanup:
            cleanup.execute(
                sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(schema_name))
            )


def test_inferred_memory_requires_explicit_confirmation_and_audits_it(memory_environment):
    repository, connection, _ = memory_environment
    memory_id = repository.create(
        MemoryDraft(
            "User may prefer concise reports",
            MemoryOrigin.MODEL_INFERRED,
            confidence=0.62,
        ),
        actor="local-model",
        reason="candidate extracted from repeated interactions",
    )
    with pytest.raises(InvalidMemoryTransition, match="explicit confirmation"):
        repository.transition(
            memory_id, MemoryState.ACTIVE, actor="operator", reason="try activate"
        )
    candidate = repository.get(memory_id)
    assert candidate.origin is MemoryOrigin.MODEL_INFERRED
    assert candidate.state is MemoryState.CANDIDATE

    repository.confirm(memory_id, actor="user", reason="user explicitly confirmed")
    active = repository.get(memory_id)
    assert active.origin is MemoryOrigin.USER_CONFIRMED
    assert active.state is MemoryState.ACTIVE
    assert active.confirmed_by == "user"
    confirmed_event = connection.execute(
        """
        SELECT previous_origin, new_origin, previous_state, new_state
          FROM memory_state_events
         WHERE memory_id = %s AND action = 'confirmed'
        """,
        (memory_id,),
    ).fetchone()
    assert confirmed_event == ("model_inferred", "user_confirmed", "candidate", "active")
    assert connection.execute(
        "SELECT count(*) FROM memory_state_events WHERE memory_id = %s",
        (memory_id,),
    ).fetchone()[0] == 2


def test_source_derived_memory_retains_immutable_evidence(memory_environment):
    repository, connection, version_id = memory_environment
    evidence = MemoryEvidence(version_id, locator="paragraph:7")
    memory_id = repository.create(
        MemoryDraft("Source-backed fact", MemoryOrigin.SOURCE_DERIVED, evidence=(evidence,)),
        actor="extractor",
    )
    repository.confirm(memory_id, actor="user", reason="reviewed source and confirmed")
    record = repository.get(memory_id)
    assert record.evidence == (evidence,)
    with pytest.raises(RaiseException, match="append-only"):
        connection.execute("DELETE FROM memory_evidence WHERE memory_id = %s", (memory_id,))
    connection.rollback()


def test_memory_state_machine_rejects_terminal_reactivation(memory_environment):
    repository, _, _ = memory_environment
    memory_id = repository.create(
        MemoryDraft("A user-authored note", MemoryOrigin.USER_AUTHORED, state=MemoryState.ACTIVE),
        actor="user",
    )
    repository.transition(memory_id, MemoryState.ARCHIVED, actor="user", reason="no longer needed")
    with pytest.raises(InvalidMemoryTransition, match="not allowed"):
        repository.transition(memory_id, MemoryState.ACTIVE, actor="user", reason="restore")


def test_memory_transition_history_is_append_only(memory_environment):
    repository, connection, _ = memory_environment
    memory_id = repository.create(
        MemoryDraft("A note", MemoryOrigin.USER_AUTHORED, state=MemoryState.ACTIVE), actor="user"
    )
    with pytest.raises(RaiseException, match="append-only"):
        connection.execute(
            "UPDATE memory_state_events SET reason = 'rewritten' WHERE memory_id = %s",
            (memory_id,),
        )
    connection.rollback()
    assert repository.get(memory_id).state is MemoryState.ACTIVE
