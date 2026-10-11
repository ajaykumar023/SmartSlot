from datetime import date, datetime, time
from typing import Literal
from pydantic import BaseModel, EmailStr, Field
from .haircut_schemas import HaircutPreferencesInput
from .service_intake_schemas import ServiceIntakeInput


class DemoLogin(BaseModel):
    role: str = Field(pattern="^(customer|admin)$")
    name: str = Field(min_length=2, max_length=120)
    email: EmailStr
    business_id: int = Field(gt=0)


class BusinessOut(BaseModel):
    id: int
    name: str
    category: Literal["salon", "clinic", "repair_center", "consultant"]
    category_label: str
    description: str
    timezone: str
    staff_label: str


class BookingCreate(BaseModel):
    service_id: int
    starts_at: datetime
    name: str = Field(min_length=2, max_length=120)
    email: EmailStr
    staff_id: int | None = None
    haircut_preferences: HaircutPreferencesInput | None = None
    service_intake: ServiceIntakeInput | None = None


class SlotQuery(BaseModel):
    service_id: int
    date_from: date
    date_to: date
    staff_id: int | None = None


class WaitlistCreate(BaseModel):
    service_id: int
    preferred_date: date
    name: str = Field(min_length=2, max_length=120)
    email: EmailStr


class BusinessCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    category: Literal["salon", "clinic", "repair_center", "consultant"]
    description: str = Field(default="", max_length=500)
    timezone: str = Field(default="Asia/Kolkata", max_length=64)


class ServiceCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    description: str = Field(default="", max_length=1000)
    duration_minutes: int = Field(gt=0, le=480)
    buffer_minutes: int = Field(default=0, ge=0, le=120)


class StaffCreate(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    title: str = Field(min_length=2, max_length=100)
    service_ids: list[int] = Field(default_factory=list)


class ServiceUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    description: str | None = Field(default=None, max_length=1000)
    duration_minutes: int | None = Field(default=None, gt=0, le=480)
    buffer_minutes: int | None = Field(default=None, ge=0, le=120)
    active: bool | None = None


class StaffUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=2, max_length=100)
    active: bool | None = None


class HoursUpdate(BaseModel):
    opens_at: time | None = None
    closes_at: time | None = None
    closed: bool = False


class ArrivalUpdate(BaseModel):
    status: Literal["on_the_way", "arrived"]
    eta_minutes: int | None = Field(default=None, ge=0, le=180)


class PresenceUpdate(BaseModel):
    status: Literal["on_site", "away", "break"]


class CodeScan(BaseModel):
    code: str = Field(min_length=5, max_length=128)


class DelayRequest(BaseModel):
    eta_minutes: int = Field(ge=0, le=180)
    max_delay_minutes: int = Field(default=30, ge=15, le=30)


class SimulationRequest(BaseModel):
    scenario: Literal["gap", "fully_booked", "near_on_time"] = "gap"
    traffic_delay_minutes: int = Field(default=25, ge=0, le=75)
    max_delay_minutes: int = Field(default=30, ge=15, le=30)
    action: Literal["preview", "accept", "decline"] = "preview"


class GeoSimulationRequest(BaseModel):
    scenario: Literal["gap", "fully_booked", "near_on_time", "nearest_unqualified", "nearest_full"] = "gap"
    traffic_delay_minutes: int = Field(default=25, ge=0, le=75)
    max_delay_minutes: Literal[15, 30] = 30
    # Pre-authorized at booking; no separate acceptance screen for a move.
    auto_reroute_opt_in: bool = False


class LocationUpdate(BaseModel):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)


class TravelLocation(BaseModel):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    accuracy_meters: float = Field(ge=0, le=10000)
    captured_at: datetime


class AutoBookRequest(BaseModel):
    service_id: int
    preferred_date: date
    name: str = Field(min_length=2, max_length=120)
    email: EmailStr
    haircut_preferences: HaircutPreferencesInput | None = None
    service_intake: ServiceIntakeInput | None = None


class StaffAbsenceCreate(BaseModel):
    starts_at: datetime
    ends_at: datetime
    reason: Literal["break", "leave", "unavailable"] = "break"


class OrganizationCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    slug: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$", min_length=2, max_length=80)


class BranchAttach(BaseModel):
    target_business_id: int = Field(gt=0)
