"""Deterministic deny-by-default policy evaluator."""

from __future__ import annotations

from collections.abc import Iterable

from personal_ai_brain.policy.models import (
    AuthorizationRequest,
    DecisionKind,
    DecisionReason,
    PolicyAction,
    PolicyDecision,
    PolicyGrant,
    PolicyPurpose,
    Principal,
)


class PolicyEngine:
    """Evaluate structured authorization metadata; retrieved content is never an input."""

    def __init__(
        self,
        principals: Iterable[Principal],
        grants: Iterable[PolicyGrant],
        *,
        policy_version: int,
        available: bool = True,
    ) -> None:
        if type(policy_version) is not int or policy_version < 1:
            raise ValueError("policy_version must be a positive integer")
        if type(available) is not bool:
            raise ValueError("available must be a boolean")
        principal_rows = tuple(principals)
        grant_rows = tuple(grants)
        self._principals = {item.principal_id: item for item in principal_rows}
        self._grants = grant_rows
        self.policy_version = policy_version
        self.available = available
        if len(self._principals) != len(principal_rows):
            raise ValueError("principal IDs must be unique")
        grant_ids = [item.grant_id for item in grant_rows]
        if len(set(grant_ids)) != len(grant_ids):
            raise ValueError("grant IDs must be unique")

    def authorize(self, request: AuthorizationRequest) -> PolicyDecision:
        try:
            return self._evaluate(request)
        except Exception:
            return self._deny(DecisionReason.EVALUATION_ERROR)

    def _deny(self, reason: DecisionReason) -> PolicyDecision:
        return PolicyDecision(
            decision=DecisionKind.DENY,
            reason=reason,
            policy_version=self.policy_version,
        )

    def _evaluate(self, request: AuthorizationRequest) -> PolicyDecision:
        if not self.available:
            return self._deny(DecisionReason.POLICY_UNAVAILABLE)
        if not isinstance(request, AuthorizationRequest):
            return self._deny(DecisionReason.EVALUATION_ERROR)
        try:
            action = PolicyAction(request.action)
        except (ValueError, TypeError):
            return self._deny(DecisionReason.INVALID_ACTION)
        if request.purpose is None or (
            isinstance(request.purpose, str) and not request.purpose.strip()
        ):
            return self._deny(DecisionReason.MISSING_PURPOSE)
        try:
            purpose = PolicyPurpose(request.purpose)
        except (ValueError, TypeError):
            return self._deny(DecisionReason.UNKNOWN_PURPOSE)
        if request.resource is None:
            return self._deny(DecisionReason.MISSING_RESOURCE)
        if action is PolicyAction.EGRESS and not request.destination_provider_id:
            return self._deny(DecisionReason.PROVIDER_REQUIRED)
        if action is not PolicyAction.EGRESS and request.destination_provider_id is not None:
            return self._deny(DecisionReason.PROVIDER_MISMATCH)

        principal = self._principals.get(request.principal_id)
        if principal is None:
            return self._deny(DecisionReason.UNKNOWN_PRINCIPAL)
        if not principal.enabled:
            return self._deny(DecisionReason.PRINCIPAL_DISABLED)
        if action.value not in principal.scopes:
            return self._deny(DecisionReason.PRINCIPAL_SCOPE_MISSING)

        candidates = [
            grant for grant in self._grants
            if grant.principal_id == principal.principal_id and action in grant.actions
        ]
        if not candidates:
            return self._deny(DecisionReason.NO_MATCHING_GRANT)

        saw_expired = False
        saw_revoked = False
        saw_provider_mismatch = False
        eligible: list[PolicyGrant] = []
        for grant in candidates:
            if grant.revoked_at is not None:
                saw_revoked = True
                continue
            if grant.expires_at is not None and request.now >= grant.expires_at:
                saw_expired = True
                continue
            if purpose not in grant.purposes:
                continue
            if request.resource.classification not in grant.classifications:
                continue
            if (
                request.resource.resource_id not in grant.resource_ids
                and (
                    request.resource.root_id is None
                    or request.resource.root_id not in grant.root_ids
                )
            ):
                continue
            if action is PolicyAction.EGRESS:
                if grant.provider_id != request.destination_provider_id:
                    saw_provider_mismatch = True
                    continue
            elif grant.provider_id is not None:
                continue
            eligible.append(grant)

        if eligible:
            selected = min(eligible, key=lambda item: item.grant_id)
            return PolicyDecision(
                decision=DecisionKind.ALLOW,
                reason=DecisionReason.ALLOWED,
                policy_version=self.policy_version,
                matched_grant_id=selected.grant_id,
            )
        if saw_provider_mismatch:
            return self._deny(DecisionReason.PROVIDER_MISMATCH)
        if saw_revoked:
            return self._deny(DecisionReason.GRANT_REVOKED)
        if saw_expired:
            return self._deny(DecisionReason.GRANT_EXPIRED)
        return self._deny(DecisionReason.NO_MATCHING_GRANT)
