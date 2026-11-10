"""PostgreSQL persistence for explicit, provenance-aware memories."""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any
from uuid import UUID, uuid4

from personal_ai_brain.memory.models import (
    InvalidMemoryTransition,
    MemoryDraft,
    MemoryEvidence,
    MemoryNotFoundError,
    MemoryOrigin,
    MemoryRecord,
    MemoryState,
)


_ALLOWED_TRANSITIONS = {
    MemoryState.CANDIDATE: {MemoryState.REJECTED, MemoryState.ARCHIVED},
    MemoryState.ACTIVE: {MemoryState.STALE, MemoryState.CONFLICTED, MemoryState.ARCHIVED},
    MemoryState.STALE: {
        MemoryState.ACTIVE, MemoryState.CONFLICTED, MemoryState.REJECTED, MemoryState.ARCHIVED
    },
    MemoryState.CONFLICTED: {
        MemoryState.ACTIVE, MemoryState.STALE, MemoryState.REJECTED, MemoryState.ARCHIVED
    },
    MemoryState.REJECTED: {MemoryState.ARCHIVED},
    MemoryState.ARCHIVED: set(),
}


class PostgresMemoryRepository:
    """Stores memory state and append-only transition evidence in one transaction."""

    def __init__(self, connection_factory: Callable[[], Any], *, close_connections: bool = True) -> None:
        self._connect = connection_factory
        self._close_connections = close_connections

    @contextmanager
    def _connection(self) -> Iterator[Any]:
        connection = self._connect()
        try:
            with connection.transaction():
                yield connection
        finally:
            if self._close_connections:
                connection.close()

    @staticmethod
    def _uuid(value: str, field_name: str) -> UUID:
        try:
            return UUID(value)
        except (ValueError, TypeError, AttributeError) as exc:
            raise ValueError(f"{field_name} must be a UUID string") from exc

    @staticmethod
    def _text(value: str, field_name: str, *, maximum: int = 200) -> str:
        if not isinstance(value, str) or not value.strip() or len(value) > maximum:
            raise ValueError(f"{field_name} must be non-empty and at most {maximum} characters")
        if any(ord(character) < 0x20 or ord(character) == 0x7F for character in value):
            raise ValueError(f"{field_name} must not contain control characters")
        return value.strip()

    def create(self, draft: MemoryDraft, *, actor: str, reason: str = "created") -> str:
        if not isinstance(draft, MemoryDraft):
            raise ValueError("draft must be a MemoryDraft")
        actor = self._text(actor, "actor")
        reason = self._text(reason, "reason", maximum=1000)
        memory_id = uuid4()
        digest = hashlib.sha256(draft.content.encode("utf-8")).hexdigest()
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO memories (
                    id, content, content_sha256, origin, state, confidence, created_by
                ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (memory_id, draft.content, digest, draft.origin.value, draft.state.value,
                 draft.confidence, actor),
            )
            for evidence in draft.evidence:
                connection.execute(
                    """
                    INSERT INTO memory_evidence (
                        memory_id, asset_version_id, artifact_id, locator
                    ) VALUES (%s, %s, %s, %s)
                    """,
                    (memory_id, self._uuid(evidence.asset_version_id, "asset_version_id"),
                     self._uuid(evidence.artifact_id, "artifact_id") if evidence.artifact_id else None,
                     evidence.locator),
                )
            connection.execute(
                """
                INSERT INTO memory_state_events (
                    id, memory_id, actor, action, previous_state, new_state,
                    previous_origin, new_origin, reason
                ) VALUES (%s, %s, %s, 'created', NULL, %s, NULL, %s, %s)
                """,
                (uuid4(), memory_id, actor, draft.state.value, draft.origin.value, reason),
            )
        return str(memory_id)

    def transition(self, memory_id: str, to_state: MemoryState, *, actor: str, reason: str) -> None:
        memory_uuid = self._uuid(memory_id, "memory_id")
        actor = self._text(actor, "actor")
        reason = self._text(reason, "reason", maximum=1000)
        if not isinstance(to_state, MemoryState):
            raise ValueError("to_state must be a MemoryState value")
        with self._connection() as connection:
            row = connection.execute(
                "SELECT origin, state FROM memories WHERE id = %s FOR UPDATE", (memory_uuid,)
            ).fetchone()
            if row is None:
                raise MemoryNotFoundError(f"memory not found: {memory_id}")
            origin, previous_state = MemoryOrigin(row[0]), MemoryState(row[1])
            if to_state not in _ALLOWED_TRANSITIONS[previous_state]:
                raise InvalidMemoryTransition(
                    f"transition {previous_state.value} -> {to_state.value} is not allowed"
                )
            if origin is MemoryOrigin.MODEL_INFERRED and to_state is MemoryState.ACTIVE:
                raise InvalidMemoryTransition("model-inferred memory requires explicit confirmation")
            if origin is MemoryOrigin.SOURCE_DERIVED and to_state is MemoryState.ACTIVE:
                evidence = connection.execute(
                    "SELECT 1 FROM memory_evidence WHERE memory_id = %s LIMIT 1", (memory_uuid,)
                ).fetchone()
                if evidence is None:
                    raise InvalidMemoryTransition("source-derived memory requires evidence to activate")
            connection.execute(
                "UPDATE memories SET state = %s, updated_at = now() WHERE id = %s",
                (to_state.value, memory_uuid),
            )
            connection.execute(
                """
                INSERT INTO memory_state_events (
                    id, memory_id, actor, action, previous_state, new_state,
                    previous_origin, new_origin, reason
                ) VALUES (%s, %s, %s, 'transitioned', %s, %s, %s, %s, %s)
                """,
                (uuid4(), memory_uuid, actor, previous_state.value, to_state.value,
                 origin.value, origin.value, reason),
            )

    def confirm(self, memory_id: str, *, actor: str, reason: str) -> None:
        """Promote a candidate only through an explicit human confirmation action."""
        memory_uuid = self._uuid(memory_id, "memory_id")
        actor = self._text(actor, "actor")
        reason = self._text(reason, "reason", maximum=1000)
        with self._connection() as connection:
            row = connection.execute(
                "SELECT origin, state FROM memories WHERE id = %s FOR UPDATE", (memory_uuid,)
            ).fetchone()
            if row is None:
                raise MemoryNotFoundError(f"memory not found: {memory_id}")
            origin, previous_state = MemoryOrigin(row[0]), MemoryState(row[1])
            if origin not in {MemoryOrigin.MODEL_INFERRED, MemoryOrigin.SOURCE_DERIVED}:
                raise InvalidMemoryTransition("only inferred or source-derived candidates need confirmation")
            if previous_state is not MemoryState.CANDIDATE:
                raise InvalidMemoryTransition("only candidate memories can be confirmed")
            if origin is MemoryOrigin.SOURCE_DERIVED:
                evidence = connection.execute(
                    "SELECT 1 FROM memory_evidence WHERE memory_id = %s LIMIT 1", (memory_uuid,)
                ).fetchone()
                if evidence is None:
                    raise InvalidMemoryTransition("source-derived memory requires evidence to confirm")
            connection.execute(
                """
                UPDATE memories
                   SET origin = 'user_confirmed', state = 'active',
                       confirmed_by = %s, confirmed_at = now(), updated_at = now()
                 WHERE id = %s
                """,
                (actor, memory_uuid),
            )
            connection.execute(
                """
                INSERT INTO memory_state_events (
                    id, memory_id, actor, action, previous_state, new_state,
                    previous_origin, new_origin, reason
                ) VALUES (%s, %s, %s, 'confirmed', %s, 'active', %s, 'user_confirmed', %s)
                """,
                (uuid4(), memory_uuid, actor, previous_state.value, origin.value, reason),
            )

    def get(self, memory_id: str) -> MemoryRecord:
        memory_uuid = self._uuid(memory_id, "memory_id")
        with self._connection() as connection:
            row = connection.execute(
                """
                SELECT id, content, content_sha256, origin, state, confidence,
                       created_by, created_at, updated_at, confirmed_by, confirmed_at
                  FROM memories WHERE id = %s
                """,
                (memory_uuid,),
            ).fetchone()
            if row is None:
                raise MemoryNotFoundError(f"memory not found: {memory_id}")
            evidence_rows = connection.execute(
                """
                SELECT asset_version_id, artifact_id, locator
                  FROM memory_evidence WHERE memory_id = %s
                 ORDER BY asset_version_id, locator
                """,
                (memory_uuid,),
            ).fetchall()
        evidence = tuple(
            MemoryEvidence(str(item[0]), str(item[1]) if item[1] else None, item[2])
            for item in evidence_rows
        )
        return MemoryRecord(
            memory_id=str(row[0]), content=row[1], content_sha256=str(row[2]).strip(),
            origin=MemoryOrigin(row[3]), state=MemoryState(row[4]), confidence=row[5],
            created_by=row[6], created_at=row[7], updated_at=row[8],
            confirmed_by=row[9], confirmed_at=row[10], evidence=evidence,
        )
