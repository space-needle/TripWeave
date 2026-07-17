from __future__ import annotations

import argparse
import logging
from pathlib import Path

from tripweave.adapters.blob_store_factory import create_blob_store
from tripweave.config import get_settings
from tripweave.domain.storage import BlobRef
from tripweave.logging import configure_logging

logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(description="TripWeave provider-neutral backup helper")
    subcommands = parser.add_subparsers(dest="command", required=True)

    upload = subcommands.add_parser("upload", help="Upload a local backup file to BlobStore")
    upload.add_argument("--file", required=True, help="Local backup file path")
    upload.add_argument("--store-alias", required=True, help="Logical backup store alias")
    upload.add_argument("--object-key", required=True, help="Logical backup object key")
    upload.add_argument(
        "--content-type",
        default="application/vnd.postgresql.dump",
        help="Backup content type",
    )

    download = subcommands.add_parser("download", help="Download a BlobStore backup file")
    download.add_argument("--store-alias", required=True, help="Logical backup store alias")
    download.add_argument("--object-key", required=True, help="Logical backup object key")
    download.add_argument("--file", required=True, help="Local output file path")

    args = parser.parse_args()
    settings = get_settings()
    configure_logging(settings.log_level)
    blob_store = create_blob_store(settings)

    if args.command == "upload":
        source = Path(args.file)
        blob_ref = BlobRef(store_alias=args.store_alias, object_key=args.object_key)
        with source.open("rb") as handle:
            metadata = blob_store.put(
                blob_ref,
                handle,
                max_size_bytes=source.stat().st_size,
                content_type=args.content_type,
            )
        logger.info(
            "backup uploaded",
            extra={
                "store_alias": metadata.blob_ref.store_alias,
                "object_key": metadata.blob_ref.object_key,
                "size_bytes": metadata.size_bytes,
                "checksum_algorithm": metadata.checksum_algorithm,
                "checksum": metadata.checksum,
            },
        )
        return

    output = Path(args.file)
    output.parent.mkdir(parents=True, exist_ok=True)
    blob_ref = BlobRef(store_alias=args.store_alias, object_key=args.object_key)
    with blob_store.open_reader(blob_ref) as reader, output.open("wb") as handle:
        while chunk := reader.read(1024 * 1024):
            handle.write(chunk)
    logger.info(
        "backup downloaded",
        extra={
            "store_alias": blob_ref.store_alias,
            "object_key": blob_ref.object_key,
            "path": str(output),
            "size_bytes": output.stat().st_size,
        },
    )


if __name__ == "__main__":
    main()
