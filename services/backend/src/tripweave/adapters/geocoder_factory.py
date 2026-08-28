from tripweave.adapters.google_geocoder import GoogleGeocoder
from tripweave.adapters.google_places_geocoder import GooglePlacesNearbyGeocoder
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
        case "google":
            if not settings.google_geocoding_api_key.strip():
                raise ValueError(
                    "TRIPWEAVE_GOOGLE_GEOCODING_API_KEY is required when "
                    "TRIPWEAVE_GEOCODER_ADAPTER=google"
                )
            return GoogleGeocoder(
                api_key=settings.google_geocoding_api_key,
                endpoint=settings.google_geocoding_endpoint,
                language=settings.google_geocoding_language,
                timeout_seconds=settings.google_geocoding_timeout_seconds,
                min_interval_seconds=settings.google_geocoding_min_interval_seconds,
            )
        case "google_places":
            if not settings.google_places_api_key.strip():
                raise ValueError(
                    "TRIPWEAVE_GOOGLE_PLACES_API_KEY is required when "
                    "TRIPWEAVE_GEOCODER_ADAPTER=google_places"
                )
            return GooglePlacesNearbyGeocoder(
                api_key=settings.google_places_api_key,
                endpoint=settings.google_places_nearby_endpoint,
                language_code=settings.google_places_language_code,
                radius_meters=settings.google_places_radius_meters,
                max_result_count=settings.google_places_max_result_count,
                timeout_seconds=settings.google_places_timeout_seconds,
                min_interval_seconds=settings.google_places_min_interval_seconds,
            )
        case _:
            raise ValueError(f"Unsupported geocoder adapter: {settings.geocoder_adapter}")
