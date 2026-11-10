"""Persistence-agnostic models for durable processing jobs."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any


class JobStatus(StrEnum):
    QUEUED = "queued"
    LEASED = "leased"
    RUNNING = "running"
    RETRY_WAIT = "retry_wait"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCEL_REQUESTED = "cancel_requested"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class JobSpec:
    asset_version_id: str
    task_type: str
    semantic_version: str
    config_digest: str
    idempotency_key: str
    payload: dict[str, Any]
    required_capabilities: tuple[str, ...] = ()
    priority: int = 0
    max_attempts: int = 3

    def __post_init__(self) -> None:
        for field_name in ("asset_version_id", "task_type", "semantic_version", "idempotency_key"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field_name} must be a non-empty string")
        if not isinstance(self.config_digest, str) or not re.fullmatch(r"[0-9a-f]{64}", self.config_digest):
            raise ValueError("config_digest must be a lowercase SHA-256 hex digest")
        if not isinstance(self.payload, dict):
            raise ValueError("payload must be a JSON object")
        if type(self.priority) is not int:
            raise ValueError("priority must be an integer")
        if type(self.max_attempts) is not int or not 1 <= self.max_attempts <= 20:
            raise ValueError("max_attempts must be between 1 and 20")
        if any(not isinstance(item, str) or not item.strip() for item in self.required_capabilities):
            raise ValueError("required_capabilities must contain non-empty strings")
        if len(set(self.required_capabilities)) != len(self.required_capabilities):
            raise ValueError("required_capabilities must not contain duplicates")


@dataclass(frozen=True, slots=True)
class JobLease:
    job_id: str
    worker_id: str
    asset_version_id: str
    task_type: str
    semantic_version: str
    config_digest: str
    payload: dict[str, Any]
    attempt_no: int
    generation: int
    expires_at: datetime


class LeaseLostError(RuntimeError):
    """The worker no longer owns the current unexpired lease."""


class PermanentJobError(RuntimeError):
    """A handler failure that must not be retried."""
