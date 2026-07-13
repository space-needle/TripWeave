from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class BlobRef:
    store_alias: str
    object_key: str
    checksum_algorithm: str | None = None
    checksum: str | None = None
    size_bytes: int | None = None
    content_type: str | None = None

    def __post_init__(self) -> None:
        if not self.store_alias:
            raise ValueError("store_alias is required")
        if not self.object_key:
            raise ValueError("object_key is required")
        if self.size_bytes is not None and self.size_bytes < 0:
            raise ValueError("size_bytes must be non-negative")
