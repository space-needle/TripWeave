#!/usr/bin/env sh
set -eu

PLATFORM="${TRIPWEAVE_PROD_PLATFORM:-linux/arm64}"
WEB_MAP_STYLE="${NEXT_PUBLIC_TRIPWEAVE_MAP_STYLE_URL:-https://tiles.openfreemap.org/styles/positron}"
WEB_API_BASE="${PUBLIC_API_BASE_URL:-https://example.com/api}"

docker buildx build \
  --platform "$PLATFORM" \
  --output=type=cacheonly \
  -f deploy/postgis.Dockerfile \
  .

docker buildx build \
  --platform "$PLATFORM" \
  --output=type=cacheonly \
  --build-arg BACKEND_DEPENDENCY_GROUPS=oci \
  services/backend

docker buildx build \
  --platform "$PLATFORM" \
  --output=type=cacheonly \
  --build-arg "NEXT_PUBLIC_API_BASE_URL=$WEB_API_BASE" \
  --build-arg "NEXT_PUBLIC_TRIPWEAVE_MAP_STYLE_URL=$WEB_MAP_STYLE" \
  -f apps/web/Dockerfile \
  .
