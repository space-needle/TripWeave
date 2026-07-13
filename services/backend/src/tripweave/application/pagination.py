from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PageRequest:
    limit: int = 50
    offset: int = 0

    def __post_init__(self) -> None:
        if self.limit < 1 or self.limit > 500:
            raise ValueError("limit must be between 1 and 500")
        if self.offset < 0:
            raise ValueError("offset must be non-negative")


@dataclass(frozen=True, slots=True)
class Page[T]:
    items: tuple[T, ...]
    limit: int
    offset: int
    total: int | None = None

    @property
    def has_more(self) -> bool:
        if self.total is None:
            return len(self.items) == self.limit
        return self.offset + len(self.items) < self.total
