from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from personal_ai_brain.policy.engine import PolicyEngine
from personal_ai_brain.policy.models import (
    AuthorizationRequest,
    DataClassification,
    DecisionKind,
    DecisionReason,
    PolicyAction,
    PolicyGrant,
    PolicyPurpose,
    PolicyResource,
    Principal,
    PrincipalKind,
)


def make_principal(*, enabled: bool = True) -> Principal:
    return Principal(
        principal_id=str(uuid4()),
        kind=PrincipalKind.AI_CLIENT,
        display_name="local assistant",
        scopes=frozenset({PolicyAction.READ_CONTENT.value, PolicyAction.EGRESS.value}),
        enabled=enabled,
    )


def make_resource() -> PolicyResource:
    return PolicyResource(
        resource_type="asset",
        resource_id=str(uuid4()),
        root_id=str(uuid4()),
        classification=DataClassification.PERSONAL,
    )


def make_grant(principal: Principal, resource: PolicyResource, **overrides) -> PolicyGrant:
    values = {
        "grant_id": str(uuid4()),
        "principal_id": principal.principal_id,
        "actions": frozenset({PolicyAction.READ_CONTENT}),
        "purposes": frozenset({PolicyPurpose.ASSISTANT_ANSWER}),
        "classifications": frozenset({DataClassification.PERSONAL}),
        "resource_ids": frozenset({resource.resource_id}),
    }
    values.update(overrides)
    return PolicyGrant(**values)


def request(
    principal: Principal, default_resource: PolicyResource, **overrides
) -> AuthorizationRequest:
    values = {
        "principal_id": principal.principal_id,
        "action": PolicyAction.READ_CONTENT,
        "resource": default_resource,
        "purpose": PolicyPurpose.ASSISTANT_ANSWER,
        "now": datetime(2026, 1, 1, tzinfo=UTC),
    }
    values.update(overrides)
    return AuthorizationRequest(**values)


def test_matching_principal_action_purpose_classification_and_resource_allow() -> None:
    principal = make_principal()
    resource = make_resource()
    grant = make_grant(principal, resource)
    engine = PolicyEngine([principal], [grant], policy_version=3)

    decision = engine.authorize(request(principal, resource))

    assert decision.decision is DecisionKind.ALLOW
    assert decision.reason is DecisionReason.ALLOWED
    assert decision.policy_version == 3
    assert decision.matched_grant_id == grant.grant_id


@pytest.mark.parametrize(
    ("request_changes", "expected_reason"),
    [
        ({"purpose": None}, DecisionReason.MISSING_PURPOSE),
        ({"purpose": " "}, DecisionReason.MISSING_PURPOSE),
        ({"resource": None}, DecisionReason.MISSING_RESOURCE),
        ({"action": "delete_original"}, DecisionReason.INVALID_ACTION),
    ],
)
def test_missing_or_invalid_request_fields_deny(request_changes, expected_reason) -> None:
    principal = make_principal()
    resource = make_resource()
    engine = PolicyEngine([principal], [make_grant(principal, resource)], policy_version=1)

    decision = engine.authorize(request(principal, resource, **request_changes))

    assert decision.decision is DecisionKind.DENY
    assert decision.reason is expected_reason


def test_unknown_and_disabled_principals_deny() -> None:
    principal = make_principal()
    resource = make_resource()
    grant = make_grant(principal, resource)
    unknown = request(principal, resource, principal_id=str(uuid4()))
    disabled = make_principal(enabled=False)
    disabled_grant = make_grant(disabled, resource)

    assert PolicyEngine([principal], [grant], policy_version=1).authorize(unknown).reason is (
        DecisionReason.UNKNOWN_PRINCIPAL
    )
    assert PolicyEngine([disabled], [disabled_grant], policy_version=1).authorize(
        request(disabled, resource)
    ).reason is DecisionReason.PRINCIPAL_DISABLED



def test_principal_scope_missing_denies_even_when_a_matching_grant_exists() -> None:
    principal = Principal(
        principal_id=str(uuid4()),
        kind=PrincipalKind.AI_CLIENT,
        display_name="metadata-only client",
        scopes=frozenset({PolicyAction.READ_METADATA.value}),
    )
    resource = make_resource()
    grant = make_grant(principal, resource)
    decision = PolicyEngine([principal], [grant], policy_version=1).authorize(
        request(principal, resource)
    )
    assert decision.reason is DecisionReason.PRINCIPAL_SCOPE_MISSING


def test_scope_purpose_classification_and_resource_mismatches_deny() -> None:
    principal = make_principal()
    resource = make_resource()
    grant = make_grant(principal, resource)
    engine = PolicyEngine([principal], [grant], policy_version=1)

    assert engine.authorize(
        request(principal, resource, purpose=PolicyPurpose.PERSONAL_SEARCH)
    ).reason is DecisionReason.NO_MATCHING_GRANT
    assert engine.authorize(
        request(principal, resource, purpose="raw prompt text must not be a purpose")
    ).reason is DecisionReason.UNKNOWN_PURPOSE
    assert engine.authorize(
        request(
            principal,
            PolicyResource(
                "asset", resource.resource_id, DataClassification.RESTRICTED, resource.root_id
            ),
        )
    ).reason is DecisionReason.NO_MATCHING_GRANT
    assert engine.authorize(
        request(
            principal,
            PolicyResource(
                "asset", str(uuid4()), DataClassification.PERSONAL, str(uuid4())
            ),
        )
    ).reason is DecisionReason.NO_MATCHING_GRANT


def test_root_scoped_grant_and_expiry_and_revocation_are_enforced() -> None:
    principal = make_principal()
    resource = make_resource()
    now = datetime(2026, 1, 1, tzinfo=UTC)
    root_grant = make_grant(
        principal,
        resource,
        resource_ids=frozenset(),
        root_ids=frozenset({resource.root_id}),
    )
    assert PolicyEngine([principal], [root_grant], policy_version=1).authorize(
        request(principal, resource, now=now)
    ).allowed

    expired = make_grant(
        principal,
        resource,
        expires_at=now - timedelta(seconds=1),
    )
    assert PolicyEngine([principal], [expired], policy_version=1).authorize(
        request(principal, resource, now=now)
    ).reason is DecisionReason.GRANT_EXPIRED

    revoked = make_grant(principal, resource, revoked_at=now - timedelta(seconds=1))
    assert PolicyEngine([principal], [revoked], policy_version=1).authorize(
        request(principal, resource, now=now)
    ).reason is DecisionReason.GRANT_REVOKED


def test_egress_is_provider_specific_and_denied_without_exact_provider_match() -> None:
    principal = make_principal()
    resource = make_resource()
    grant = make_grant(
        principal,
        resource,
        actions=frozenset({PolicyAction.EGRESS}),
        provider_id="provider-a",
    )
    engine = PolicyEngine([principal], [grant], policy_version=7)

    assert engine.authorize(
        request(principal, resource, action=PolicyAction.EGRESS)
    ).reason is DecisionReason.PROVIDER_REQUIRED
    assert engine.authorize(
        request(
            principal,
            resource,
            action=PolicyAction.EGRESS,
            destination_provider_id="provider-b",
        )
    ).reason is DecisionReason.PROVIDER_MISMATCH
    assert engine.authorize(
        request(
            principal,
            resource,
            action=PolicyAction.EGRESS,
            destination_provider_id="provider-a",
        )
    ).allowed


def test_policy_unavailable_and_no_grant_fail_closed() -> None:
    principal = make_principal()
    resource = make_resource()
    request_value = request(principal, resource)

    unavailable = PolicyEngine([principal], [], policy_version=1, available=False)
    empty = PolicyEngine([principal], [], policy_version=1)

    assert unavailable.authorize(request_value).reason is DecisionReason.POLICY_UNAVAILABLE
    assert empty.authorize(request_value).reason is DecisionReason.NO_MATCHING_GRANT


def test_engine_never_accepts_document_content_as_policy_input() -> None:
    principal = make_principal()
    resource = make_resource()
    grant = make_grant(principal, resource)
    engine = PolicyEngine([principal], [grant], policy_version=1)
    assert engine.authorize(request(principal, resource)).allowed
