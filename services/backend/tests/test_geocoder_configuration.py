from tripweave.adapters.geocoder_factory import create_geocoder
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
