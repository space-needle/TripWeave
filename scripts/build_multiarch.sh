#!/usr/bin/env sh
set -eu

PLATFORMS="${TRIPWEAVE_BUILD_PLATFORMS:-linux/amd64,linux/arm64}"
WEB_MAP_STYLE="${NEXT_PUBLIC_TRIPWEAVE_MAP_STYLE_URL:-https://tiles.openfreemap.org/styles/positron}"
WEB_API_BASE="${NEXT_PUBLIC_API_BASE_URL:-http://localhost:8000}"

docker buildx build \
  --platform "$PLATFORMS" \
  --output=type=cacheonly \
  -f deploy/postgis.Dockerfile \
  .

docker buildx build \
  --platform "$PLATFORMS" \
  --output=type=cacheonly \
  services/backend

docker buildx build \
  --platform "$PLATFORMS" \
  --output=type=cacheonly \
  --build-arg "NEXT_PUBLIC_API_BASE_URL=$WEB_API_BASE" \
  --build-arg "NEXT_PUBLIC_TRIPWEAVE_MAP_STYLE_URL=$WEB_MAP_STYLE" \
  -f apps/web/Dockerfile \
  .
