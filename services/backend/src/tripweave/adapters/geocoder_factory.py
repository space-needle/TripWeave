from tripweave.adapters.manual_geocoder import ManualGeocoder
from tripweave.adapters.nominatim_geocoder import NominatimGeocoder
from tripweave.config import Settings
from tripweave.ports.geocoder import Geocoder


def create_geocoder(settings: Settings) -> Geocoder:
    match settings.geocoder_adapter:
        case "manual":
            return ManualGeocoder()
        case "nominatim":
            return NominatimGeocoder(
                endpoint=settings.nominatim_endpoint,
                user_agent=settings.nominatim_user_agent,
                accept_language=settings.nominatim_accept_language,
                timeout_seconds=settings.nominatim_timeout_seconds,
                min_interval_seconds=settings.nominatim_min_interval_seconds,
            )
        case _:
            raise ValueError(f"Unsupported geocoder adapter: {settings.geocoder_adapter}")
