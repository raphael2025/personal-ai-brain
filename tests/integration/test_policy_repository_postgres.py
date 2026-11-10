"""PostgreSQL tests for versioned policy grants and redacted audit."""

from __future__ import annotations

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

from personal_ai_brain.policy.models import (  # noqa: E402
    AuthorizationRequest,
    DataClassification,
    DecisionKind,
    DecisionReason,
    PolicyAction,
    PolicyGrant,
    PolicyResource,
    Principal,
    PrincipalKind,
)
from personal_ai_brain.policy.repository import PostgresPolicyRepository  # noqa: E402

MIGRATIONS = [
    Path(__file__).parents[2] / "infrastructure/postgres/migrations/0001_asset_registry.sql",
    Path(__file__).parents[2] / "infrastructure/postgres/migrations/0006_policy_engine.sql",
]


@pytest.fixture
def policy_environment():
    connection = psycopg.connect(DATABASE_URL)
    schema_name = f"brain_policy_test_{uuid4().hex}"
    try:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema_name)))
        connection.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(schema_name)))
        for migration in MIGRATIONS:
            connection.execute(migration.read_text(encoding="utf-8"))
        connection.commit()

        def connect():
            return psycopg.connect(DATABASE_URL, options=f"-c search_path={schema_name}")

        yield PostgresPolicyRepository(connect), connection
    finally:
        connection.rollback()
        connection.close()
        with psycopg.connect(DATABASE_URL) as cleanup:
            cleanup.execute(
                sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(schema_name))
            )


def test_policy_repository_versions_grants_and_revocation_blocks_next_request(policy_environment):
    repository, connection = policy_environment
    principal = Principal(
        principal_id=str(uuid4()),
        kind=PrincipalKind.AI_CLIENT,
        display_name="local assistant",
        scopes=frozenset({PolicyAction.READ_CONTENT.value}),
    )
    resource_id, root_id = str(uuid4()), str(uuid4())
    resource = PolicyResource("asset", resource_id, DataClassification.PERSONAL, root_id)
    grant = PolicyGrant(
        grant_id=str(uuid4()),
        principal_id=principal.principal_id,
        actions=frozenset({PolicyAction.READ_CONTENT}),
        purposes=frozenset({"assistant_answer"}),
        classifications=frozenset({DataClassification.PERSONAL}),
        resource_ids=frozenset({resource_id}),
    )

    repository.register_principal(principal, actor="admin")
    repository.create_grant(grant, actor="admin")
    allowed = repository.authorize(
        AuthorizationRequest(
            principal_id=principal.principal_id,
            action=PolicyAction.READ_CONTENT,
            resource=resource,
            purpose="assistant_answer",
        )
    )
    assert allowed.decision is DecisionKind.ALLOW
    assert allowed.policy_version == 3

    assert repository.revoke_grant(grant.grant_id, actor="admin") is True
    denied = repository.authorize(
        AuthorizationRequest(
            principal_id=principal.principal_id,
            action=PolicyAction.READ_CONTENT,
            resource=resource,
            purpose="assistant_answer",
        )
    )
    assert denied.decision is DecisionKind.DENY
    assert denied.reason is DecisionReason.GRANT_REVOKED
    assert denied.policy_version == 4

    decisions = connection.execute(
        """
        SELECT decision, reason_code, policy_version
          FROM policy_decisions
         ORDER BY occurred_at, request_id
        """
    ).fetchall()
    assert {row[0] for row in decisions} == {"allow", "deny"}
    assert {row[2] for row in decisions} == {3, 4}
    assert connection.execute("SELECT count(*) FROM policy_admin_events").fetchone()[0] == 3


def test_unknown_principal_is_audited_as_denied_without_content(policy_environment):
    repository, connection = policy_environment
    decision = repository.authorize(
        AuthorizationRequest(
            principal_id=str(uuid4()),
            action=PolicyAction.SEARCH,
            resource=PolicyResource(
                "asset", str(uuid4()), DataClassification.SENSITIVE, str(uuid4())
            ),
            purpose="personal_search",
        )
    )
    assert decision.reason is DecisionReason.UNKNOWN_PRINCIPAL
    row = connection.execute(
        "SELECT decision, reason_code, purpose FROM policy_decisions"
    ).fetchone()
    assert row == ("deny", "unknown_principal", "personal_search")
    columns = connection.execute(
        """
        SELECT column_name FROM information_schema.columns
         WHERE table_schema = current_schema() AND table_name = 'policy_decisions'
        """
    ).fetchall()
    assert "document_body" not in {item[0] for item in columns}
    assert "prompt" not in {item[0] for item in columns}


def test_admin_and_decision_audit_are_append_only(policy_environment):
    repository, connection = policy_environment
    principal = Principal(
        principal_id=str(uuid4()),
        kind=PrincipalKind.USER,
        display_name="owner",
        scopes=frozenset(),
    )
    repository.register_principal(principal, actor="bootstrap")
    with pytest.raises(RaiseException, match="append-only"):
        connection.execute("UPDATE policy_admin_events SET actor = 'rewritten'")
    connection.rollback()
    assert repository.set_principal_enabled(principal.principal_id, False, actor="admin")
