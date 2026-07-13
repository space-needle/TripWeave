from tripweave.ports.geocoder import GeocodeResult


class ManualGeocoder:
    """Local no-op geocoder. Names can be filled by humans later."""

    def name_for_point(self, *, latitude: float, longitude: float) -> GeocodeResult:
        return GeocodeResult(name=None, confidence=None)
