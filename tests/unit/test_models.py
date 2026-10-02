from app.infrastructure.db.base import Base
from app.modules.audit.models import AuditEvent


def test_audit_model_is_registered() -> None:
    assert AuditEvent.__tablename__ == "audit_events"
    assert "audit_events" in Base.metadata.tables
    assert Base.metadata.tables["audit_events"].c.request_id.index is True
