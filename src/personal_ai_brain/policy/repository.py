"""PostgreSQL persistence and transactional audit for policy decisions."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any
from uuid import UUID

from personal_ai_brain.policy.engine import PolicyEngine
from personal_ai_brain.policy.models import (
    AuthorizationRequest,
    DataClassification,
    DecisionKind,
    DecisionReason,
    PolicyAction,
    PolicyDecision,
    PolicyGrant,
    Principal,
    PrincipalKind,
)


class PostgresPolicyRepository:
    """Policy mutations and decisions share a version lock and append-only audit."""

    def __init__(self, connection_factory: Callable[[], Any], *, close_connections: bool = True):
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
    def _actor(actor: str) -> str:
        if not isinstance(actor, str) or not actor.strip() or len(actor) > 200:
            raise ValueError("actor must be non-empty and at most 200 characters")
        if any(ord(character) < 0x20 or ord(character) == 0x7F for character in actor):
            raise ValueError("actor must not contain control characters")
        return actor.strip()

    @staticmethod
    def _lock_policy_version(connection: Any) -> int:
        row = connection.execute(
            "SELECT version FROM policy_state WHERE singleton = TRUE FOR UPDATE"
        ).fetchone()
        if row is None:
            raise RuntimeError("policy state row is missing")
        return int(row[0])

    @staticmethod
    def _bump_policy_version(connection: Any) -> int:
        row = connection.execute(
            """
            UPDATE policy_state
               SET version = version + 1, updated_at = now()
             WHERE singleton = TRUE
            RETURNING version
            """
        ).fetchone()
        if row is None:
            raise RuntimeError("policy state row is missing")
        return int(row[0])

    @staticmethod
    def _admin_event(
        connection: Any,
        *,
        actor: str,
        action: str,
        target_type: str,
        target_id: str,
        policy_version: int,
    ) -> None:
        connection.execute(
            """
            INSERT INTO policy_admin_events (
                actor, action, target_type, target_id, policy_version
            ) VALUES (%s, %s, %s, %s, %s)
            """,
            (actor, action, target_type, UUID(target_id), policy_version),
        )

    def register_principal(self, principal: Principal, *, actor: str) -> None:
        actor = self._actor(actor)
        with self._connection() as connection:
            self._lock_policy_version(connection)
            connection.execute(
                """
                INSERT INTO policy_principals (
                    id, principal_kind, display_name, scopes, enabled,
                    owner_principal_id, created_by
                ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    UUID(principal.principal_id),
                    principal.kind.value,
                    principal.display_name,
                    sorted(principal.scopes),
                    principal.enabled,
                    UUID(principal.owner_principal_id) if principal.owner_principal_id else None,
                    actor,
                ),
            )
            version = self._bump_policy_version(connection)
            self._admin_event(
                connection, actor=actor, action="principal_registered",
                target_type="principal", target_id=principal.principal_id,
                policy_version=version,
            )

    def set_principal_enabled(self, principal_id: str, enabled: bool, *, actor: str) -> bool:
        principal_uuid = self._uuid(principal_id, "principal_id")
        if type(enabled) is not bool:
            raise ValueError("enabled must be a boolean")
        actor = self._actor(actor)
        with self._connection() as connection:
            self._lock_policy_version(connection)
            row = connection.execute(
                """
                UPDATE policy_principals
                   SET enabled = %s, updated_at = now()
                 WHERE id = %s AND enabled IS DISTINCT FROM %s
                RETURNING id
                """,
                (enabled, principal_uuid, enabled),
            ).fetchone()
            if row is None:
                return False
            version = self._bump_policy_version(connection)
            self._admin_event(
                connection,
                actor=actor,
                action="principal_enabled" if enabled else "principal_disabled",
                target_type="principal",
                target_id=principal_id,
                policy_version=version,
            )
            return True

    def create_grant(self, grant: PolicyGrant, *, actor: str) -> None:
        actor = self._actor(actor)
        if grant.revoked_at is not None:
            raise ValueError("a revoked grant cannot be created")
        with self._connection() as connection:
            self._lock_policy_version(connection)
            connection.execute(
                """
                INSERT INTO policy_grants (
                    id, principal_id, actions, purposes, classifications,
                    resource_ids, root_ids, provider_id, expires_at, created_by
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    UUID(grant.grant_id),
                    UUID(grant.principal_id),
                    sorted(item.value for item in grant.actions),
                    sorted(grant.purposes),
                    sorted(item.value for item in grant.classifications),
                    [UUID(item) for item in sorted(grant.resource_ids)],
                    [UUID(item) for item in sorted(grant.root_ids)],
                    grant.provider_id,
                    grant.expires_at,
                    actor,
                ),
            )
            version = self._bump_policy_version(connection)
            self._admin_event(
                connection, actor=actor, action="grant_created",
                target_type="policy_grant", target_id=grant.grant_id,
                policy_version=version,
            )

    def revoke_grant(self, grant_id: str, *, actor: str) -> bool:
        grant_uuid = self._uuid(grant_id, "grant_id")
        actor = self._actor(actor)
        with self._connection() as connection:
            self._lock_policy_version(connection)
            row = connection.execute(
                """
                UPDATE policy_grants
                   SET revoked_at = now(), revoked_by = %s
                 WHERE id = %s AND revoked_at IS NULL
                RETURNING id
                """,
                (actor, grant_uuid),
            ).fetchone()
            if row is None:
                return False
            version = self._bump_policy_version(connection)
            self._admin_event(
                connection, actor=actor, action="grant_revoked",
                target_type="policy_grant", target_id=grant_id,
                policy_version=version,
            )
            return True

    def authorize(self, request: AuthorizationRequest) -> PolicyDecision:
        """Authorize and append a redacted decision before returning it to the caller."""
        try:
            with self._connection() as connection:
                version_row = connection.execute(
                    "SELECT version FROM policy_state WHERE singleton = TRUE FOR SHARE"
                ).fetchone()
                if version_row is None:
                    raise RuntimeError("policy state row is missing")
                policy_version = int(version_row[0])
                principal_rows = connection.execute(
                    """
                    SELECT id, principal_kind, display_name, scopes, enabled, owner_principal_id
                      FROM policy_principals
                    """
                ).fetchall()
                grant_rows = connection.execute(
                    """
                    SELECT id, principal_id, actions, purposes, classifications,
                           resource_ids, root_ids, provider_id, expires_at, revoked_at
                      FROM policy_grants
                    """
                ).fetchall()
                principals = [
                    Principal(
                        principal_id=str(row[0]),
                        kind=PrincipalKind(row[1]),
                        display_name=row[2],
                        scopes=frozenset(row[3]),
                        enabled=row[4],
                        owner_principal_id=str(row[5]) if row[5] else None,
                    )
                    for row in principal_rows
                ]
                grants = [
                    PolicyGrant(
                        grant_id=str(row[0]),
                        principal_id=str(row[1]),
                        actions=frozenset(PolicyAction(value) for value in row[2]),
                        purposes=frozenset(row[3]),
                        classifications=frozenset(
                            DataClassification(value) for value in row[4]
                        ),
                        resource_ids=frozenset(str(value) for value in row[5]),
                        root_ids=frozenset(str(value) for value in row[6]),
                        provider_id=row[7],
                        expires_at=row[8],
                        revoked_at=row[9],
                    )
                    for row in grant_rows
                ]
                engine = PolicyEngine(
                    principals, grants, policy_version=policy_version
                )
                decision = engine.authorize(request)
                resource = request.resource
                principal_uuid = self._uuid_or_none(request.principal_id)
                resource_uuid = (
                    self._uuid_or_none(resource.resource_id) if resource else None
                )
                root_uuid = self._uuid_or_none(resource.root_id) if resource else None
                connection.execute(
                    """
                    INSERT INTO policy_decisions (
                        request_id, principal_id, action, resource_type, resource_id,
                        root_id, classification, purpose, destination_provider_id,
                        decision, reason_code, policy_version, matched_grant_id
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        UUID(request.request_id),
                        principal_uuid,
                        request.action.value if isinstance(request.action, PolicyAction)
                        else str(request.action),
                        resource.resource_type if resource else None,
                        resource_uuid,
                        root_uuid,
                        resource.classification.value if resource else None,
                        request.purpose,
                        request.destination_provider_id,
                        decision.decision.value,
                        decision.reason.value,
                        decision.policy_version,
                        UUID(decision.matched_grant_id) if decision.matched_grant_id else None,
                    ),
                )
                return decision
        except Exception:
            return PolicyDecision(
                decision=DecisionKind.DENY,
                reason=DecisionReason.POLICY_UNAVAILABLE,
                policy_version=0,
            )

    @staticmethod
    def _uuid_or_none(value: str | None) -> UUID | None:
        if value is None:
            return None
        try:
            return UUID(value)
        except (ValueError, TypeError, AttributeError):
            return None
