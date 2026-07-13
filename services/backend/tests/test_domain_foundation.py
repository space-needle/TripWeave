from dataclasses import fields
from typing import cast

import pytest
from sqlalchemy import Table

from tripweave.adapters.orm import Base, MediaItem
from tripweave.domain.enums import UploadState
from tripweave.domain.storage import BlobRef
from tripweave.domain.upload_state import (
    can_transition_upload_state,
    require_upload_state_transition,
)


def test_blob_ref_is_provider_neutral() -> None:
    field_names = {field.name for field in fields(BlobRef)}

    assert field_names == {
        "store_alias",
        "object_key",
        "checksum_algorithm",
        "checksum",
        "size_bytes",
        "content_type",
    }
    assert BlobRef(store_alias="media_private", object_key="trips/t1/original.jpg").object_key


def test_blob_ref_rejects_empty_storage_identity() -> None:
    with pytest.raises(ValueError, match="store_alias"):
        BlobRef(store_alias="", object_key="key")

    with pytest.raises(ValueError, match="object_key"):
        BlobRef(store_alias="media_private", object_key="")


def test_upload_state_transitions_are_explicit() -> None:
    assert can_transition_upload_state(UploadState.REGISTERING, UploadState.REGISTERED)
    assert can_transition_upload_state(UploadState.REGISTERED, UploadState.TRANSFERRING)
    assert can_transition_upload_state(UploadState.TRANSFERRING, UploadState.TRANSFERRED)
    assert can_transition_upload_state(UploadState.TRANSFERRED, UploadState.VERIFYING)
    assert can_transition_upload_state(UploadState.VERIFYING, UploadState.VERIFIED)
    assert can_transition_upload_state(UploadState.VERIFIED, UploadState.COMPLETED)

    with pytest.raises(ValueError, match="cannot transition"):
        require_upload_state_transition(UploadState.COMPLETED, UploadState.TRANSFERRING)


def test_schema_has_expected_domain_tables() -> None:
    assert set(Base.metadata.tables) == {
        "guest_sessions",
        "media_assets",
        "media_items",
        "moment_media",
        "moment_participants",
        "moments",
        "places",
        "processing_jobs",
        "reconstruction_runs",
        "review_items",
        "sessions",
        "stops",
        "trip_days",
        "trip_invitations",
        "trip_legs",
        "trip_members",
        "trips",
        "upload_files",
        "upload_sessions",
        "users",
    }


def test_schema_does_not_persist_provider_specific_storage_fields() -> None:
    forbidden_fragments = {
        "bucket",
        "namespace",
        "provider_url",
        "par_url",
        "presigned_url",
        "signed_url",
    }
    columns = {column.name for table in Base.metadata.tables.values() for column in table.columns}

    assert not {
        column
        for column in columns
        for forbidden_fragment in forbidden_fragments
        if forbidden_fragment in column
    }


def test_media_items_keep_original_and_effective_metadata_separate() -> None:
    columns = set(MediaItem.__table__.columns.keys())

    assert {
        "original_captured_at_local",
        "original_captured_at_utc",
        "original_utc_offset_minutes",
        "effective_captured_at_utc",
        "original_location",
        "effective_location",
        "time_source",
        "location_source",
        "time_confidence",
        "location_confidence",
    }.issubset(columns)


def test_geographic_columns_have_gist_indexes() -> None:
    media_items_table = cast(Table, MediaItem.__table__)
    indexes = {cast(str, index.name): index for index in media_items_table.indexes}

    assert (
        indexes["ix_media_items_original_location_gist"].dialect_options["postgresql"]["using"]
        == "gist"
    )
    assert (
        indexes["ix_media_items_effective_location_gist"].dialect_options["postgresql"]["using"]
        == "gist"
    )
