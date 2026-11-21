from uuid import UUID

from neatsprint_lib.ids import is_uuid7, new_id, parse_id


def test_new_id_is_uuid7() -> None:
    value = new_id()
    assert isinstance(value, UUID)
    assert value.version == 7
    assert is_uuid7(str(value))


def test_ids_sort_in_creation_order() -> None:
    ids = [new_id() for _ in range(100)]
    assert ids == sorted(ids)


def test_parse_id_rejects_garbage() -> None:
    try:
        parse_id("not-a-uuid")
    except ValueError:
        pass
    else:  # pragma: no cover
        raise AssertionError("expected ValueError")


def test_is_uuid7_rejects_v4() -> None:
    assert not is_uuid7("9f1c1b7e-3a2d-4c5b-8e6f-0a1b2c3d4e5f")
