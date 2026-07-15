from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from http.cookiejar import CookieJar
from pathlib import Path
from typing import Any


API_BASE = os.environ.get("TRIPWEAVE_LOCAL_API", "http://localhost:8000").rstrip("/")
WEB_BASE = os.environ.get("TRIPWEAVE_LOCAL_WEB", "http://localhost:3000").rstrip("/")
CLOUD_SDK_MARKERS = ("boto3", "botocore", "google-cloud", "oci==", "@aws-sdk", "aws-sdk")


class Client:
    def __init__(self) -> None:
        self.cookies = CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.cookies))
        self.csrf = ""

    def request(self, method: str, url: str, body: Any | None = None) -> tuple[int, Any]:
        headers = {"x-request-id": "local-smoke"}
        data = None
        if self.csrf:
            headers["x-csrf-token"] = self.csrf
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["content-type"] = "application/json"
        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            response = self.opener.open(request, timeout=20)
            payload = response.read()
            status = response.status
        except urllib.error.HTTPError as exc:
            payload = exc.read()
            status = exc.code
        try:
            decoded: Any = json.loads(payload.decode("utf-8")) if payload else None
        except json.JSONDecodeError:
            decoded = payload.decode("utf-8", errors="replace")
        return status, decoded


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def check_no_cloud_sdks() -> None:
    root = Path(__file__).resolve().parents[1]
    lock_text = "\n".join(
        path.read_text(encoding="utf-8", errors="ignore")
        for path in [root / "services/backend/uv.lock", root / "pnpm-lock.yaml"]
        if path.exists()
    ).lower()
    for marker in CLOUD_SDK_MARKERS:
        require(marker.lower() not in lock_text, f"Cloud SDK marker found in lock files: {marker}")


def main() -> None:
    client = Client()
    ready_status, ready_body = client.request("GET", f"{API_BASE}/health/ready")
    require(ready_status == 200 and ready_body["ready"], "API readiness failed")

    web_status, _ = client.request("GET", WEB_BASE)
    require(web_status == 200, "Web app did not respond")

    email = "smoke@tripweave.local"
    registered_status, registered_body = client.request(
        "POST",
        f"{API_BASE}/auth/register",
        {"email": email, "password": "local-smoke-password", "displayName": "Smoke"},
    )
    if registered_status == 201:
        client.csrf = registered_body["csrfToken"]
    else:
        login_status, login_body = client.request(
            "POST",
            f"{API_BASE}/auth/login",
            {"email": email, "password": "local-smoke-password"},
        )
        require(login_status == 200, f"Smoke auth failed: {login_status} {login_body}")
        client.csrf = login_body["csrfToken"]

    ops_status, ops_body = client.request("GET", f"{API_BASE}/ops/local-mvp")
    require(ops_status == 200 and "jobStates" in ops_body, "Ops summary failed")
    check_no_cloud_sdks()
    print(json.dumps({"ready": True, "api": API_BASE, "web": WEB_BASE}, indent=2))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"local smoke failed: {exc}", file=sys.stderr)
        raise
