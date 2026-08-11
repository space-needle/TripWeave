from tripweave.application.timezone_lookup import timezone_for_coordinates


def test_timezone_lookup_resolves_korea_and_california_locally() -> None:
    assert timezone_for_coordinates(37.5665, 126.9780) == "Asia/Seoul"
    assert timezone_for_coordinates(34.0522, -118.2437) == "America/Los_Angeles"


def test_timezone_lookup_rejects_invalid_coordinates() -> None:
    assert timezone_for_coordinates(91, 0) is None
    assert timezone_for_coordinates(0, -181) is None
