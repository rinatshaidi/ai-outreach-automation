"""Fail-closed owner safety policy tests."""

from app.infrastructure.db.base import Base
from app.modules.safety.models import OwnerSafetyPolicy


def test_owner_safety_policy_is_fail_closed() -> None:
    policy = OwnerSafetyPolicy(owner_key="primary")

    assert policy.real_send_enabled is None
    assert "owner_safety_policies" in Base.metadata.tables
    column = Base.metadata.tables["owner_safety_policies"].c.real_send_enabled
    assert column.nullable is False
    assert column.default is not None
