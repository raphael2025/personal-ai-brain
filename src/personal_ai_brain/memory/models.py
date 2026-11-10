"""Persistence-agnostic models for explicit personal memory lifecycle."""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID


class MemoryOrigin(StrEnum):
    USER_AUTHORED = "user_authored"
    USER_CONFIRMED = "user_confirmed"
    SOURCE_DERIVED = "source_derived"
    MODEL_INFERRED = "model_inferred"


class MemoryState(StrEnum):
    CANDIDATE = "candidate"
    ACTIVE = "active"
    STALE = "stale"
    CONFLICTED = "conflicted"
    REJECTED = "rejected"
    ARCHIVED = "archived"


@dataclass(frozen=True, slots=True)
class MemoryEvidence:
    """A pointer to an immutable source version and optional derived artifact."""

    asset_version_id: str
    artifact_id: str | None = None
    locator: str = "document"

    def __post_init__(self) -> None:
        for name in ("asset_version_id", "artifact_id"):
            value = getattr(self, name)
            if value is None and name == "artifact_id":
                continue
            try:
                UUID(value)
            except (ValueError, TypeError, AttributeError) as exc:
                raise ValueError(f"{name} must be a UUID string") from exc
        if (
            not isinstance(self.locator, str)
            or not self.locator.strip()
            or len(self.locator) > 1000
        ):
            raise ValueError("locator must be non-empty and at most 1000 characters")
        if any(ord(character) < 0x20 and character not in "\t\n" for character in self.locator):
            raise ValueError("locator must not contain control characters")


@dataclass(frozen=True, slots=True)
class MemoryDraft:
    """A proposed memory; model inference is never implicitly trusted."""

    content: str
    origin: MemoryOrigin
    state: MemoryState = MemoryState.CANDIDATE
    confidence: float | None = None
    evidence: tuple[MemoryEvidence, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.content, str) or not self.content.strip():
            raise ValueError("content must be a non-empty string")
        if len(self.content) > 20_000:
            raise ValueError("content must be at most 20000 characters")
        if "\x00" in self.content:
            raise ValueError("content must not contain NUL")
        if not isinstance(self.origin, MemoryOrigin):
            raise ValueError("origin must be a MemoryOrigin value")
        if not isinstance(self.state, MemoryState):
            raise ValueError("state must be a MemoryState value")
        if self.origin is MemoryOrigin.USER_CONFIRMED:
            raise ValueError(
                "user-confirmed memories must be created through explicit confirmation"
            )
        if (
            self.origin in {MemoryOrigin.MODEL_INFERRED, MemoryOrigin.SOURCE_DERIVED}
            and self.state is not MemoryState.CANDIDATE
        ):
            raise ValueError("inferred and source-derived memories must start as candidates")
        if self.origin is MemoryOrigin.SOURCE_DERIVED and not self.evidence:
            raise ValueError("source-derived memories require at least one evidence reference")
        if any(not isinstance(item, MemoryEvidence) for item in self.evidence):
            raise ValueError("evidence must contain MemoryEvidence values")
        evidence_keys = {(item.asset_version_id, item.locator) for item in self.evidence}
        if len(evidence_keys) != len(self.evidence):
            raise ValueError("evidence references must not duplicate a source version and locator")
        if self.confidence is not None:
            if isinstance(self.confidence, bool) or not isinstance(self.confidence, (int, float)):
                raise ValueError("confidence must be a number between 0 and 1")
            if not math.isfinite(self.confidence) or not 0 <= self.confidence <= 1:
                raise ValueError("confidence must be a finite number between 0 and 1")


@dataclass(frozen=True, slots=True)
class MemoryRecord:
    memory_id: str
    content: str
    content_sha256: str
    origin: MemoryOrigin
    state: MemoryState
    confidence: float | None
    created_by: str
    created_at: object
    updated_at: object
    confirmed_by: str | None
    confirmed_at: object | None
    evidence: tuple[MemoryEvidence, ...]


class InvalidMemoryTransition(ValueError):
    """The requested memory lifecycle transition is not permitted."""


class MemoryNotFoundError(LookupError):
    """The requested memory does not exist."""
