from datetime import UTC, datetime
from uuid import uuid4

from neatsprint_lib.events import OutboxEvent, to_message


def test_outbox_message_contains_envelope() -> None:
    tenant_id = uuid4()
    event = OutboxEvent(
        id=uuid4(),
        tenant_id=tenant_id,
        actor_id=None,
        event_type="item.created",
        event_version=1,
        payload={"item_id": "abc"},
        occurred_at=datetime(2026, 11, 21, 10, 0, tzinfo=UTC),
    )
    message = to_message(event)
    assert message["event_id"] == str(event.id)
    assert message["event_type"] == "item.created"
    assert message["tenant_id"] == str(tenant_id)
    assert message["actor_id"] == ""
    assert message["occurred_at"].startswith("2026-11-21T10:00:00")
    assert '"item_id": "abc"' in message["data"]
