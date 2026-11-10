"""Typed policy inputs, grants, and decisions."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID, uuid4


class PrincipalKind(StrEnum):
    USER = "user"
    AI_CLIENT = "ai_client"
    WORKER = "worker"
    SERVICE = "service"
    PROVIDER = "provider"


class DataClassification(StrEnum):
    PUBLIC = "public"
    PERSONAL = "personal"
    SENSITIVE = "sensitive"
    RESTRICTED = "restricted"


class PolicyAction(StrEnum):
    READ_METADATA = "read_metadata"
    READ_CONTENT = "read_content"
    SEARCH = "search"
    MEMORY_CONFIRM = "memory_confirm"
    EGRESS = "egress"


class PolicyPurpose(StrEnum):
    ASSISTANT_ANSWER = "assistant_answer"
    PERSONAL_SEARCH = "personal_search"
    MEMORY_CONFIRMATION = "memory_confirmation"
    LOCAL_EXTRACTION = "local_extraction"
    EXTERNAL_MODEL_EGRESS = "external_model_egress"
    ADMINISTRATION = "administration"


class DecisionKind(StrEnum):
    ALLOW = "allow"
    DENY = "deny"


class DecisionReason(StrEnum):
    ALLOWED = "allowed"
    POLICY_UNAVAILABLE = "policy_unavailable"
    UNKNOWN_PRINCIPAL = "unknown_principal"
    PRINCIPAL_DISABLED = "principal_disabled"
    MISSING_PURPOSE = "missing_purpose"
    UNKNOWN_PURPOSE = "unknown_purpose"
    INVALID_ACTION = "invalid_action"
    MISSING_RESOURCE = "missing_resource"
    PRINCIPAL_SCOPE_MISSING = "principal_scope_missing"
    NO_MATCHING_GRANT = "no_matching_grant"
    GRANT_EXPIRED = "grant_expired"
    GRANT_REVOKED = "grant_revoked"
    PROVIDER_REQUIRED = "provider_required"
    PROVIDER_MISMATCH = "provider_mismatch"
    EVALUATION_ERROR = "evaluation_error"


def _uuid(value: str, field_name: str) -> None:
    try:
        UUID(value)
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValueError(f"{field_name} must be a UUID string") from exc


def _safe_text(value: str, field_name: str, *, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError(f"{field_name} must be non-empty and at most {maximum} characters")
    if any(ord(character) < 0x20 or ord(character) == 0x7F for character in value):
        raise ValueError(f"{field_name} must not contain control characters")
    return value.strip()


def _aware(value: datetime | None, field_name: str) -> None:
    if value is not None and (
        not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None
    ):
        raise ValueError(f"{field_name} must be timezone-aware")


@dataclass(frozen=True, slots=True)
class Principal:
    principal_id: str
    kind: PrincipalKind
    display_name: str
    scopes: frozenset[str] = frozenset()
    enabled: bool = True
    owner_principal_id: str | None = None

    def __post_init__(self) -> None:
        _uuid(self.principal_id, "principal_id")
        if self.owner_principal_id is not None:
            _uuid(self.owner_principal_id, "owner_principal_id")
        if not isinstance(self.kind, PrincipalKind):
            raise ValueError("kind must be a PrincipalKind value")
        _safe_text(self.display_name, "display_name", maximum=200)
        if type(self.enabled) is not bool:
            raise ValueError("enabled must be a boolean")
        if any(
            not isinstance(scope, str)
            or not scope.strip()
            or len(scope) > 128
            or any(ord(character) < 0x20 for character in scope)
            for scope in self.scopes
        ):
            raise ValueError("scopes must contain non-empty safe strings of at most 128 characters")


@dataclass(frozen=True, slots=True)
class PolicyResource:
    resource_type: str
    resource_id: str
    classification: DataClassification
    root_id: str | None = None

    def __post_init__(self) -> None:
        _safe_text(self.resource_type, "resource_type", maximum=64)
        if self.resource_type not in {
            "storage_root", "asset", "asset_version", "artifact", "memory",
            "search_result", "context_bundle",
        }:
            raise ValueError("resource_type is not a supported resource identifier")
        _uuid(self.resource_id, "resource_id")
        if self.root_id is not None:
            _uuid(self.root_id, "root_id")
        if not isinstance(self.classification, DataClassification):
            raise ValueError("classification must be a DataClassification value")


@dataclass(frozen=True, slots=True)
class PolicyGrant:
    grant_id: str
    principal_id: str
    actions: frozenset[PolicyAction]
    purposes: frozenset[str]
    classifications: frozenset[DataClassification]
    resource_ids: frozenset[str] = frozenset()
    root_ids: frozenset[str] = frozenset()
    provider_id: str | None = None
    expires_at: datetime | None = None
    revoked_at: datetime | None = None

    def __post_init__(self) -> None:
        _uuid(self.grant_id, "grant_id")
        _uuid(self.principal_id, "principal_id")
        if not self.actions or any(not isinstance(item, PolicyAction) for item in self.actions):
            raise ValueError("actions must contain PolicyAction values")
        if not self.purposes:
            raise ValueError("purposes must not be empty")
        if any(not isinstance(purpose, PolicyPurpose) for purpose in self.purposes):
            raise ValueError("purposes must contain PolicyPurpose values")
        if not self.classifications or any(
            not isinstance(item, DataClassification) for item in self.classifications
        ):
            raise ValueError("classifications must contain DataClassification values")
        for resource_id in self.resource_ids:
            _uuid(resource_id, "resource_id")
        for root_id in self.root_ids:
            _uuid(root_id, "root_id")
        if not self.resource_ids and not self.root_ids:
            raise ValueError("grant must name at least one resource ID or root ID")
        if PolicyAction.EGRESS in self.actions:
            if self.actions != frozenset({PolicyAction.EGRESS}) or self.provider_id is None:
                raise ValueError("egress grants must be provider-specific and contain only egress")
            _safe_text(self.provider_id, "provider_id", maximum=200)
        elif self.provider_id is not None:
            raise ValueError("provider_id is only valid for egress grants")
        _aware(self.expires_at, "expires_at")
        _aware(self.revoked_at, "revoked_at")


@dataclass(frozen=True, slots=True)
class AuthorizationRequest:
    principal_id: str
    action: PolicyAction | str
    resource: PolicyResource | None
    purpose: str | None
    destination_provider_id: str | None = None
    request_id: str = field(default_factory=lambda: str(uuid4()))
    now: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        _safe_text(self.principal_id, "principal_id", maximum=128)
        _uuid(self.request_id, "request_id")
        if isinstance(self.action, str):
            _safe_text(self.action, "action", maximum=64)
        if self.purpose is not None and (
            not isinstance(self.purpose, str)
            or len(self.purpose) > 128
            or any(ord(character) < 0x20 or ord(character) == 0x7F for character in self.purpose)
        ):
            raise ValueError("purpose must be a safe string of at most 128 characters")
        if self.destination_provider_id is not None:
            _safe_text(self.destination_provider_id, "destination_provider_id", maximum=200)
        _aware(self.now, "now")
        if self.resource is not None and not isinstance(self.resource, PolicyResource):
            raise ValueError("resource must be a PolicyResource or None")


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    decision: DecisionKind
    reason: DecisionReason
    policy_version: int
    matched_grant_id: str | None = None

    @property
    def allowed(self) -> bool:
        return self.decision is DecisionKind.ALLOW
