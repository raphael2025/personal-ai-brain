from __future__ import annotations

from uuid import uuid4

import pytest

from personal_ai_brain.memory.models import (
    MemoryDraft,
    MemoryEvidence,
    MemoryOrigin,
    MemoryState,
)


def test_model_inference_must_start_as_candidate() -> None:
    with pytest.raises(ValueError, match="candidates"):
        MemoryDraft("likes tea", MemoryOrigin.MODEL_INFERRED, state=MemoryState.ACTIVE)


def test_source_derived_memory_requires_evidence_and_starts_candidate() -> None:
    with pytest.raises(ValueError, match="evidence"):
        MemoryDraft("project deadline is Friday", MemoryOrigin.SOURCE_DERIVED)
    with pytest.raises(ValueError, match="candidates"):
        MemoryDraft(
            "project deadline is Friday",
            MemoryOrigin.SOURCE_DERIVED,
            state=MemoryState.ACTIVE,
            evidence=(MemoryEvidence(str(uuid4())),),
        )


def test_user_confirmed_origin_cannot_be_forged_at_creation() -> None:
    with pytest.raises(ValueError, match="explicit confirmation"):
        MemoryDraft("confirmed fact", MemoryOrigin.USER_CONFIRMED)


def test_memory_evidence_requires_uuid_and_safe_locator() -> None:
    with pytest.raises(ValueError, match="UUID"):
        MemoryEvidence("not-a-uuid")
    with pytest.raises(ValueError, match="control"):
        MemoryEvidence(str(uuid4()), locator="page\\x00secret")


def test_confidence_must_be_finite_and_bounded() -> None:
    for value in (-0.1, 1.1, float("nan"), float("inf"), True):
        with pytest.raises(ValueError, match="confidence"):
            MemoryDraft("fact", MemoryOrigin.USER_AUTHORED, confidence=value)


def test_source_derived_candidate_accepts_exact_source_evidence() -> None:
    evidence = MemoryEvidence(str(uuid4()), locator="page:4/paragraph:2")
    draft = MemoryDraft(
        "A source-backed fact", MemoryOrigin.SOURCE_DERIVED, evidence=(evidence,)
    )
    assert draft.evidence == (evidence,)


def test_duplicate_evidence_locator_is_rejected_even_if_artifact_differs() -> None:
    version = str(uuid4())
    first = MemoryEvidence(version, str(uuid4()), "paragraph:1")
    second = MemoryEvidence(version, str(uuid4()), "paragraph:1")
    with pytest.raises(ValueError, match="duplicate"):
        MemoryDraft("fact", MemoryOrigin.SOURCE_DERIVED, evidence=(first, second))
