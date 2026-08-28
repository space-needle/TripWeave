import pytest

from tripweave.adapters.geocoder_factory import create_geocoder
from tripweave.adapters.google_geocoder import GoogleGeocoder
from tripweave.adapters.google_places_geocoder import GooglePlacesNearbyGeocoder
from tripweave.adapters.manual_geocoder import ManualGeocoder
from tripweave.adapters.nominatim_geocoder import NominatimGeocoder
from tripweave.config import Settings


def test_manual_geocoder_is_default() -> None:
    settings = Settings()

    assert settings.geocoder_adapter == "manual"
    assert isinstance(create_geocoder(settings), ManualGeocoder)


def test_nominatim_geocoder_can_be_selected() -> None:
    settings = Settings(TRIPWEAVE_GEOCODER_ADAPTER="nominatim")

    assert isinstance(create_geocoder(settings), NominatimGeocoder)


def test_google_geocoder_can_be_selected() -> None:
    settings = Settings(
        TRIPWEAVE_GEOCODER_ADAPTER="google",
        TRIPWEAVE_GOOGLE_GEOCODING_API_KEY="test-key",
    )

    assert isinstance(create_geocoder(settings), GoogleGeocoder)


def test_google_geocoder_requires_an_api_key() -> None:
    settings = Settings(TRIPWEAVE_GEOCODER_ADAPTER="google")

    with pytest.raises(ValueError, match="TRIPWEAVE_GOOGLE_GEOCODING_API_KEY"):
        create_geocoder(settings)


def test_google_places_nearby_geocoder_can_be_selected() -> None:
    settings = Settings(
        TRIPWEAVE_GEOCODER_ADAPTER="google_places",
        TRIPWEAVE_GOOGLE_PLACES_API_KEY="test-key",
    )

    assert isinstance(create_geocoder(settings), GooglePlacesNearbyGeocoder)


def test_google_places_nearby_geocoder_requires_an_api_key() -> None:
    settings = Settings(TRIPWEAVE_GEOCODER_ADAPTER="google_places")

    with pytest.raises(ValueError, match="TRIPWEAVE_GOOGLE_PLACES_API_KEY"):
        create_geocoder(settings)
