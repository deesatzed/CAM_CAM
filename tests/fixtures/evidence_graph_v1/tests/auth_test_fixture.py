from auth_service import validate_token


def test_validate_token_rejects_empty_value() -> None:
    assert validate_token("") is False
