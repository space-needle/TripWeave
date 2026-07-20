from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from http.cookiejar import CookieJar
from io import BytesIO
from typing import Any

from PIL import ExifTags, Image


API_BASE = os.environ.get("TRIPWEAVE_LOCAL_API", "http://localhost:8000").rstrip("/")
OWNER_EMAIL = os.environ.get("TRIPWEAVE_DEMO_OWNER_EMAIL", "owner.demo@tripweave.local")
PASSWORD = os.environ.get("TRIPWEAVE_DEMO_PASSWORD", "local-demo-password")


@dataclass
class ApiResponse:
    status: int
    body: Any
    headers: dict[str, str]


class ApiClient:
    def __init__(self) -> None:
        self.cookies = CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.cookies)
        )
        self.csrf_token = ""

    def request(
        self,
        method: str,
        path: str,
        *,
        body: Any | None = None,
        headers: dict[str, str] | None = None,
        raw: bytes | None = None,
    ) -> ApiResponse:
        request_headers = {"x-request-id": f"seed-demo-{int(time.time() * 1000)}"}
        if headers:
            request_headers.update(headers)
        data: bytes | None = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            request_headers["content-type"] = "application/json"
        if raw is not None:
            data = raw
        url = f"{API_BASE}{path}"
        request = urllib.request.Request(
            url, data=data, headers=request_headers, method=method
        )
        try:
            response = self.opener.open(request, timeout=30)
            payload = response.read()
            status = response.status
            response_headers = dict(response.headers.items())
        except urllib.error.HTTPError as exc:
            payload = exc.read()
            status = exc.code
            response_headers = dict(exc.headers.items())
        if not payload:
            decoded: Any = None
        else:
            try:
                decoded = json.loads(payload.decode("utf-8"))
            except json.JSONDecodeError:
                decoded = payload.decode("utf-8", errors="replace")
        return ApiResponse(status=status, body=decoded, headers=response_headers)

    def json(self, method: str, path: str, body: Any | None = None) -> Any:
        headers = {"x-csrf-token": self.csrf_token} if self.csrf_token else {}
        response = self.request(method, path, body=body, headers=headers)
        if response.status >= 400:
            raise RuntimeError(
                f"{method} {path} failed: {response.status} {response.body}"
            )
        return response.body


def gps_degrees(value: float) -> tuple[float, float, float]:
    absolute = abs(value)
    degrees = int(absolute)
    minutes_float = (absolute - degrees) * 60
    minutes = int(minutes_float)
    seconds = (minutes_float - minutes) * 60
    return (float(degrees), float(minutes), seconds)


def jpeg_fixture(
    *,
    color: str,
    captured_at: str | None,
    latitude: float | None,
    longitude: float | None,
    make: str,
    model: str,
) -> bytes:
    image = Image.new("RGB", (96, 72), color)
    exif = Image.Exif()
    exif[271] = make
    exif[272] = model
    if captured_at:
        exif[306] = captured_at
        exif[36867] = captured_at
        exif[36868] = captured_at
        exif[36881] = "+09:00"
    if latitude is not None and longitude is not None:
        gps_ifd = {
            1: "N" if latitude >= 0 else "S",
            2: gps_degrees(latitude),
            3: "E" if longitude >= 0 else "W",
            4: gps_degrees(longitude),
        }
        exif[ExifTags.IFD.GPSInfo] = gps_ifd
    output = BytesIO()
    image.save(output, format="JPEG", exif=exif)
    return output.getvalue()


def ensure_owner(client: ApiClient) -> None:
    registered = client.request(
        "POST",
        "/auth/register",
        body={
            "email": OWNER_EMAIL,
            "password": PASSWORD,
            "displayName": "Demo Owner",
        },
    )
    if registered.status == 201:
        client.csrf_token = str(registered.body["csrfToken"])
        return
    logged_in = client.request(
        "POST",
        "/auth/login",
        body={"email": OWNER_EMAIL, "password": PASSWORD},
    )
    if logged_in.status != 200:
        raise RuntimeError(f"Could not register or log in demo owner: {logged_in.body}")
    client.csrf_token = str(logged_in.body["csrfToken"])


def create_trip(client: ApiClient) -> dict[str, Any]:
    trips = client.json("GET", "/trips")
    for trip in trips.get("trips", []):
        if trip["title"] == "Local MVP Demo":
            return dict(trip)
    return dict(
        client.json(
            "POST",
            "/trips",
            {
                "title": "Local MVP Demo",
                "description": "Deterministic local MVP release-candidate fixture.",
                "startDate": "2026-06-06",
                "endDate": "2026-06-08",
                "timezoneId": "Asia/Tokyo",
                "dayCutoffHour": 4,
            },
        )
    )


def accept_contributor(owner: ApiClient, trip_id: str, display_name: str) -> ApiClient:
    invitation = owner.json("POST", f"/trips/{trip_id}/invitations", {})
    token = str(invitation["inviteUrl"]).rsplit("/", 1)[-1]
    contributor = ApiClient()
    email = f"{display_name.lower().replace(' ', '.')}@demo.tripweave.local"
    registered = contributor.request(
        "POST",
        "/auth/register",
        body={
            "email": email,
            "password": PASSWORD,
            "displayName": display_name,
        },
    )
    if registered.status not in {200, 201}:
        logged_in = contributor.request(
            "POST", "/auth/login", body={"email": email, "password": PASSWORD}
        )
        if logged_in.status != 200:
            raise RuntimeError(
                f"Contributor account failed: {registered.status} {registered.body}"
            )
        contributor.csrf_token = str(logged_in.body["csrfToken"])
    else:
        contributor.csrf_token = str(registered.body["csrfToken"])
    accepted = contributor.request(
        "POST",
        f"/invitations/{token}/accept",
        body={},
        headers={"x-csrf-token": contributor.csrf_token},
    )
    if accepted.status != 200:
        raise RuntimeError(
            f"Contributor invitation failed: {accepted.status} {accepted.body}"
        )
    return contributor


def upload(client: ApiClient, trip_id: str, filename: str, payload: bytes) -> None:
    session = client.json(
        "POST",
        f"/trips/{trip_id}/upload-sessions",
        {
            "files": [
                {
                    "filename": filename,
                    "byteSize": len(payload),
                    "mimeType": "image/jpeg",
                }
            ]
        },
    )
    upload_file = session["files"][0]
    grant = upload_file["grant"]
    upload_url = urllib.parse.urlparse(grant["url"])
    put_path = upload_url.path
    put = client.request("PUT", put_path, raw=payload, headers=grant["headers"])
    if put.status != 200:
        raise RuntimeError(f"Upload failed for {filename}: {put.status} {put.body}")
    client.json("POST", f"/upload-files/{upload_file['id']}/complete")


def wait_for_worker(
    client: ApiClient, expected_ready: int, timeout_seconds: int = 120
) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        media = client.json("GET", "/trips")
        _ = media
        ops = client.json("GET", "/ops/local-mvp")
        ready = int(ops.get("mediaStates", {}).get("ready", 0))
        failed = int(ops.get("mediaStates", {}).get("failed", 0))
        if ready >= expected_ready and failed >= 1:
            return
        time.sleep(2)
    raise TimeoutError("Worker did not finish demo media in time")


def main() -> None:
    owner = ApiClient()
    ensure_owner(owner)
    trip = create_trip(owner)
    trip_id = str(trip["id"])
    contributor_one = accept_contributor(owner, trip_id, "Demo Contributor One")
    contributor_two = accept_contributor(owner, trip_id, "Demo Contributor Two")

    fixtures = [
        (
            owner,
            "owner-day1-a.jpg",
            jpeg_fixture(
                color="red",
                captured_at="2026:06:06 10:00:00",
                latitude=35.6812,
                longitude=139.7671,
                make="TripWeaveCam",
                model="Owner",
            ),
        ),
        (
            owner,
            "owner-after-midnight.jpg",
            jpeg_fixture(
                color="orange",
                captured_at="2026:06:07 01:10:00",
                latitude=35.6813,
                longitude=139.7672,
                make="TripWeaveCam",
                model="Owner",
            ),
        ),
        (
            contributor_one,
            "contributor1-day2-nogps.jpg",
            jpeg_fixture(
                color="blue",
                captured_at="2026:06:07 11:00:00",
                latitude=None,
                longitude=None,
                make="OffsetCam",
                model="Behind15m",
            ),
        ),
        (
            contributor_one,
            "contributor1-offset-match.jpg",
            jpeg_fixture(
                color="green",
                captured_at="2026:06:07 11:15:00",
                latitude=35.6895,
                longitude=139.6917,
                make="OffsetCam",
                model="Behind15m",
            ),
        ),
        (
            contributor_two,
            "contributor2-day2-match.jpg",
            jpeg_fixture(
                color="green",
                captured_at="2026:06:07 11:30:00",
                latitude=35.6895,
                longitude=139.6917,
                make="TripWeaveCam",
                model="ContributorTwo",
            ),
        ),
        (
            contributor_two,
            "contributor2-day3.jpg",
            jpeg_fixture(
                color="purple",
                captured_at="2026:06:08 13:00:00",
                latitude=35.7101,
                longitude=139.8107,
                make="TripWeaveCam",
                model="ContributorTwo",
            ),
        ),
    ]
    duplicate = fixtures[0][2]
    fixtures.append((contributor_two, "exact-duplicate.jpg", duplicate))
    fixtures.append((owner, "corrupt.jpg", b"not really a jpeg"))

    for client, filename, payload in fixtures:
        upload(client, trip_id, filename, payload)

    wait_for_worker(owner, expected_ready=7)
    reconstruction = owner.json("POST", f"/trips/{trip_id}/reconstruction-runs")
    owner.json("POST", f"/trips/{trip_id}/publications")
    print(
        json.dumps(
            {"tripId": trip_id, "days": len(reconstruction.get("days", []))}, indent=2
        )
    )


if __name__ == "__main__":
    main()
