from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from tripweave.application.auth import normalize_email
from tripweave.domain.enums import TripStatus, TripVisibility


class UserResponse(BaseModel):
    id: UUID
    email: str
    display_name: str


class AuthResponse(BaseModel):
    user: UserResponse
    csrf_token: str = Field(alias="csrfToken")


class RegisterRequest(BaseModel):
    email: str = Field(min_length=5, max_length=320)
    password: str = Field(min_length=8, max_length=256)
    display_name: str = Field(alias="displayName", min_length=1, max_length=160)

    @field_validator("email")
    @classmethod
    def normalize(cls, value: str) -> str:
        normalized = normalize_email(value)
        if "@" not in normalized or "." not in normalized.rsplit("@", 1)[-1]:
            raise ValueError("Enter a valid email address")
        return normalized


class LoginRequest(BaseModel):
    email: str = Field(min_length=5, max_length=320)
    password: str = Field(min_length=1, max_length=256)

    @field_validator("email")
    @classmethod
    def normalize(cls, value: str) -> str:
        return normalize_email(value)


class MeResponse(BaseModel):
    user: UserResponse


class TripCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=5000)
    start_date: date | None = Field(default=None, alias="startDate")
    end_date: date | None = Field(default=None, alias="endDate")
    timezone_id: str = Field(default="UTC", alias="timezoneId", min_length=1, max_length=100)
    day_cutoff_hour: int = Field(default=4, alias="dayCutoffHour", ge=0, le=23)

    @model_validator(mode="after")
    def validate_dates(self) -> TripCreateRequest:
        if (
            self.start_date is not None
            and self.end_date is not None
            and self.end_date < self.start_date
        ):
            raise ValueError("endDate must be on or after startDate")
        return self


class TripUpdateRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=5000)
    start_date: date | None = Field(default=None, alias="startDate")
    end_date: date | None = Field(default=None, alias="endDate")
    timezone_id: str | None = Field(default=None, alias="timezoneId", min_length=1, max_length=100)
    day_cutoff_hour: int | None = Field(default=None, alias="dayCutoffHour", ge=0, le=23)
    status: str | None = Field(default=None)
    visibility: str | None = Field(default=None)

    @field_validator("status")
    @classmethod
    def validate_status(cls, value: str | None) -> str | None:
        if value is not None and value not in {item.value for item in TripStatus}:
            raise ValueError("Invalid trip status")
        return value

    @field_validator("visibility")
    @classmethod
    def validate_visibility(cls, value: str | None) -> str | None:
        if value is not None and value not in {item.value for item in TripVisibility}:
            raise ValueError("Invalid trip visibility")
        return value

    @model_validator(mode="after")
    def validate_dates(self) -> TripUpdateRequest:
        if (
            self.start_date is not None
            and self.end_date is not None
            and self.end_date < self.start_date
        ):
            raise ValueError("endDate must be on or after startDate")
        return self


class TripResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: str
    description: str | None
    start_date: date | None = Field(alias="startDate")
    end_date: date | None = Field(alias="endDate")
    timezone_id: str = Field(alias="timezoneId")
    day_cutoff_hour: int = Field(alias="dayCutoffHour")
    status: str
    visibility: str
    role: str
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")


class TripsListResponse(BaseModel):
    trips: list[TripResponse]
