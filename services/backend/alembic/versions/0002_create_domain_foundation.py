"""Create provider-neutral domain foundation.

Revision ID: 0002_create_domain_foundation
Revises: 0001_enable_postgis
Create Date: 2026-07-12
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0002_create_domain_foundation"
down_revision: str | None = "0001_enable_postgis"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE users (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            email varchar(320) NOT NULL UNIQUE,
            password_hash text NOT NULL,
            display_name varchar(160) NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT ck_users_email_normalized CHECK (email = lower(email)),
            CONSTRAINT ck_users_email_min_length CHECK (length(email) > 3)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE sessions (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            token_hash text NOT NULL UNIQUE,
            expires_at timestamptz NOT NULL,
            revoked_at timestamptz,
            created_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        """
        CREATE TABLE trips (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            title varchar(200) NOT NULL,
            description text,
            start_date date,
            end_date date,
            timezone_id varchar(100) NOT NULL,
            day_cutoff_hour integer NOT NULL DEFAULT 4,
            status varchar(40) NOT NULL DEFAULT 'draft',
            visibility varchar(40) NOT NULL DEFAULT 'private',
            created_by uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT ck_trips_day_cutoff_hour CHECK (
                day_cutoff_hour >= 0 AND day_cutoff_hour <= 23
            ),
            CONSTRAINT ck_trips_date_order CHECK (
                end_date IS NULL OR start_date IS NULL OR end_date >= start_date
            ),
            CONSTRAINT ck_trips_status CHECK (status IN ('draft', 'active', 'archived')),
            CONSTRAINT ck_trips_visibility CHECK (
                visibility IN ('private', 'shared', 'published')
            )
        )
        """
    )
    op.execute(
        """
        CREATE TABLE trip_members (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            trip_id uuid NOT NULL REFERENCES trips(id) ON DELETE CASCADE,
            user_id uuid REFERENCES users(id) ON DELETE SET NULL,
            role varchar(40) NOT NULL,
            display_name varchar(160) NOT NULL,
            joined_at timestamptz NOT NULL DEFAULT now(),
            removed_at timestamptz,
            CONSTRAINT ck_trip_members_role CHECK (
                role IN ('owner', 'contributor', 'viewer')
            ),
            CONSTRAINT ck_trip_members_guest_display_name CHECK (
                user_id IS NOT NULL OR display_name IS NOT NULL
            ),
            CONSTRAINT uq_trip_members_id_trip_id UNIQUE (id, trip_id)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE trip_invitations (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            trip_id uuid NOT NULL REFERENCES trips(id) ON DELETE CASCADE,
            email varchar(320) NOT NULL,
            role varchar(40) NOT NULL,
            token_hash text NOT NULL UNIQUE,
            status varchar(40) NOT NULL DEFAULT 'pending',
            expires_at timestamptz NOT NULL,
            accepted_at timestamptz,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT ck_trip_invitations_email_normalized CHECK (email = lower(email)),
            CONSTRAINT ck_trip_invitations_role CHECK (
                role IN ('owner', 'contributor', 'viewer')
            ),
            CONSTRAINT ck_trip_invitations_status CHECK (
                status IN ('pending', 'accepted', 'revoked', 'expired')
            )
        )
        """
    )
    op.execute(
        """
        CREATE TABLE upload_sessions (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            trip_id uuid NOT NULL REFERENCES trips(id) ON DELETE CASCADE,
            member_id uuid NOT NULL REFERENCES trip_members(id) ON DELETE RESTRICT,
            state varchar(40) NOT NULL DEFAULT 'registering',
            declared_file_count integer,
            declared_total_bytes bigint,
            registered_at timestamptz,
            transfer_started_at timestamptz,
            transferred_at timestamptz,
            verified_at timestamptz,
            completed_at timestamptz,
            cancelled_at timestamptz,
            failed_at timestamptz,
            error_message text,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT ck_upload_sessions_state CHECK (
                state IN (
                    'registering', 'registered', 'transferring', 'transferred',
                    'verifying', 'verified', 'completed', 'cancelled', 'failed'
                )
            ),
            CONSTRAINT ck_upload_sessions_file_count CHECK (
                declared_file_count IS NULL OR declared_file_count >= 0
            ),
            CONSTRAINT ck_upload_sessions_total_bytes CHECK (
                declared_total_bytes IS NULL OR declared_total_bytes >= 0
            ),
            CONSTRAINT fk_upload_sessions_member_trip FOREIGN KEY (member_id, trip_id)
                REFERENCES trip_members(id, trip_id) ON DELETE RESTRICT
        )
        """
    )
    op.execute(
        """
        CREATE TABLE media_items (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            trip_id uuid NOT NULL REFERENCES trips(id) ON DELETE CASCADE,
            contributor_member_id uuid NOT NULL REFERENCES trip_members(id) ON DELETE RESTRICT,
            media_type varchar(40) NOT NULL,
            original_filename text,
            declared_mime_type varchar(255),
            detected_mime_type varchar(255),
            byte_size bigint,
            original_store_alias varchar(100) NOT NULL,
            original_object_key text NOT NULL,
            original_captured_at_local timestamp,
            original_captured_at_utc timestamptz,
            original_utc_offset_minutes integer,
            effective_captured_at_utc timestamptz,
            original_location geography(Point,4326),
            effective_location geography(Point,4326),
            time_source varchar(40) NOT NULL DEFAULT 'unknown',
            location_source varchar(40) NOT NULL DEFAULT 'unknown',
            time_confidence double precision,
            location_confidence double precision,
            sha256 varchar(64) NOT NULL,
            perceptual_hash varchar(255),
            processing_state varchar(40) NOT NULL DEFAULT 'pending',
            visibility varchar(40) NOT NULL DEFAULT 'private',
            include_in_story boolean NOT NULL DEFAULT false,
            caption text,
            memo text,
            user_locked boolean NOT NULL DEFAULT false,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            deleted_at timestamptz,
            CONSTRAINT uq_media_items_original_store_alias UNIQUE (
                original_store_alias, original_object_key
            ),
            CONSTRAINT ck_media_items_media_type CHECK (
                media_type IN ('photo', 'video', 'other')
            ),
            CONSTRAINT ck_media_items_time_source CHECK (
                time_source IN (
                    'original_metadata', 'user_correction', 'automation', 'unknown'
                )
            ),
            CONSTRAINT ck_media_items_location_source CHECK (
                location_source IN (
                    'original_metadata', 'user_correction', 'automation', 'unknown'
                )
            ),
            CONSTRAINT ck_media_items_processing_state CHECK (
                processing_state IN ('pending', 'processing', 'ready', 'failed')
            ),
            CONSTRAINT ck_media_items_visibility CHECK (
                visibility IN ('private', 'trip', 'story', 'excluded')
            ),
            CONSTRAINT ck_media_items_byte_size CHECK (byte_size IS NULL OR byte_size >= 0),
            CONSTRAINT ck_media_items_time_confidence CHECK (
                time_confidence IS NULL OR (time_confidence >= 0 AND time_confidence <= 1)
            ),
            CONSTRAINT ck_media_items_location_confidence CHECK (
                location_confidence IS NULL
                OR (location_confidence >= 0 AND location_confidence <= 1)
            ),
            CONSTRAINT fk_media_items_contributor_trip FOREIGN KEY (
                contributor_member_id, trip_id
            ) REFERENCES trip_members(id, trip_id) ON DELETE RESTRICT
        )
        """
    )
    op.execute(
        """
        CREATE TABLE upload_files (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            upload_session_id uuid NOT NULL REFERENCES upload_sessions(id) ON DELETE CASCADE,
            media_item_id uuid REFERENCES media_items(id) ON DELETE SET NULL,
            state varchar(40) NOT NULL DEFAULT 'registered',
            original_filename text,
            declared_byte_size bigint,
            declared_mime_type varchar(255),
            detected_mime_type varchar(255),
            store_alias varchar(100) NOT NULL,
            object_key text NOT NULL,
            sha256 varchar(64),
            transfer_started_at timestamptz,
            transferred_at timestamptz,
            verified_at timestamptz,
            completed_at timestamptz,
            cancelled_at timestamptz,
            failed_at timestamptz,
            error_message text,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT uq_upload_files_store_alias UNIQUE (store_alias, object_key),
            CONSTRAINT ck_upload_files_state CHECK (
                state IN (
                    'registering', 'registered', 'transferring', 'transferred',
                    'verifying', 'verified', 'completed', 'cancelled', 'failed'
                )
            ),
            CONSTRAINT ck_upload_files_byte_size CHECK (
                declared_byte_size IS NULL OR declared_byte_size >= 0
            )
        )
        """
    )
    op.execute(
        """
        CREATE TABLE media_assets (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            media_item_id uuid NOT NULL REFERENCES media_items(id) ON DELETE CASCADE,
            asset_type varchar(40) NOT NULL,
            store_alias varchar(100) NOT NULL,
            object_key text NOT NULL,
            mime_type varchar(255) NOT NULL,
            width integer,
            height integer,
            byte_size bigint,
            checksum text,
            metadata_stripped boolean NOT NULL DEFAULT false,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT uq_media_assets_store_alias UNIQUE (store_alias, object_key),
            CONSTRAINT ck_media_assets_asset_type CHECK (
                asset_type IN ('original', 'thumbnail', 'display', 'story')
            ),
            CONSTRAINT ck_media_assets_width CHECK (width IS NULL OR width > 0),
            CONSTRAINT ck_media_assets_height CHECK (height IS NULL OR height > 0),
            CONSTRAINT ck_media_assets_byte_size CHECK (byte_size IS NULL OR byte_size >= 0)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE processing_jobs (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            job_type varchar(80) NOT NULL,
            target_type varchar(80) NOT NULL,
            target_id uuid NOT NULL,
            state varchar(40) NOT NULL DEFAULT 'pending',
            priority integer NOT NULL DEFAULT 100,
            attempts integer NOT NULL DEFAULT 0,
            max_attempts integer NOT NULL DEFAULT 3,
            run_after timestamptz NOT NULL DEFAULT now(),
            locked_at timestamptz,
            locked_by varchar(160),
            idempotency_key text NOT NULL UNIQUE,
            error_code varchar(120),
            error_message text,
            started_at timestamptz,
            finished_at timestamptz,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT ck_processing_jobs_job_type CHECK (
                job_type IN (
                    'metadata_extraction', 'alignment', 'grouping',
                    'derivative_generation', 'publication', 'deletion', 'repair'
                )
            ),
            CONSTRAINT ck_processing_jobs_target_type CHECK (
                target_type IN ('upload_file', 'media_item', 'trip', 'story_publication')
            ),
            CONSTRAINT ck_processing_jobs_state CHECK (
                state IN ('pending', 'running', 'succeeded', 'failed', 'cancelled')
            ),
            CONSTRAINT ck_processing_jobs_priority CHECK (priority >= 0),
            CONSTRAINT ck_processing_jobs_attempts CHECK (attempts >= 0),
            CONSTRAINT ck_processing_jobs_max_attempts CHECK (max_attempts > 0),
            CONSTRAINT ck_processing_jobs_attempt_budget CHECK (attempts <= max_attempts)
        )
        """
    )
    op.execute("CREATE INDEX ix_sessions_user_id ON sessions (user_id)")
    op.execute("CREATE INDEX ix_trips_created_by ON trips (created_by)")
    op.execute("CREATE INDEX ix_trip_members_trip_id ON trip_members (trip_id)")
    op.execute("CREATE INDEX ix_trip_members_user_id ON trip_members (user_id)")
    op.execute(
        """
        CREATE UNIQUE INDEX uq_trip_members_active_user
        ON trip_members (trip_id, user_id)
        WHERE removed_at IS NULL
        """
    )
    op.execute("CREATE INDEX ix_trip_invitations_trip_email ON trip_invitations (trip_id, email)")
    op.execute("CREATE INDEX ix_upload_sessions_trip_id ON upload_sessions (trip_id)")
    op.execute("CREATE INDEX ix_upload_sessions_member_id ON upload_sessions (member_id)")
    op.execute("CREATE INDEX ix_upload_files_upload_session_id ON upload_files (upload_session_id)")
    op.execute("CREATE INDEX ix_upload_files_media_item_id ON upload_files (media_item_id)")
    op.execute("CREATE INDEX ix_media_items_trip_id ON media_items (trip_id)")
    op.execute(
        """
        CREATE INDEX ix_media_items_contributor_member_id
        ON media_items (contributor_member_id)
        """
    )
    op.execute(
        """
        CREATE INDEX ix_media_items_effective_captured_at_utc
        ON media_items (effective_captured_at_utc)
        """
    )
    op.execute("CREATE INDEX ix_media_items_sha256 ON media_items (sha256)")
    op.execute(
        """
        CREATE INDEX ix_media_items_original_location_gist
        ON media_items USING gist (original_location)
        """
    )
    op.execute(
        """
        CREATE INDEX ix_media_items_effective_location_gist
        ON media_items USING gist (effective_location)
        """
    )
    op.execute("CREATE INDEX ix_media_assets_media_item_id ON media_assets (media_item_id)")
    op.execute(
        """
        CREATE INDEX ix_processing_jobs_claimable
        ON processing_jobs (state, priority, run_after)
        """
    )
    op.execute(
        """
        CREATE INDEX ix_processing_jobs_target
        ON processing_jobs (target_type, target_id)
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE processing_jobs")
    op.execute("DROP TABLE media_assets")
    op.execute("DROP TABLE upload_files")
    op.execute("DROP TABLE media_items")
    op.execute("DROP TABLE upload_sessions")
    op.execute("DROP TABLE trip_invitations")
    op.execute("DROP TABLE trip_members")
    op.execute("DROP TABLE trips")
    op.execute("DROP TABLE sessions")
    op.execute("DROP TABLE users")
