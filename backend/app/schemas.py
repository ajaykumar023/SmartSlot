from datetime import date, datetime, time
from typing import Literal
from pydantic import BaseModel, EmailStr, Field


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


class SelfCheckInRequest(BaseModel):
    token: str = Field(min_length=1, max_length=128)


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
    price: int | None = Field(default=None, ge=0)


class StaffCreate(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    title: str = Field(min_length=2, max_length=100)
    service_ids: list[int] = Field(default_factory=list)


class ServiceUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    description: str | None = Field(default=None, max_length=1000)
    duration_minutes: int | None = Field(default=None, gt=0, le=480)
    buffer_minutes: int | None = Field(default=None, ge=0, le=120)
    price: int | None = Field(default=None, ge=0)
    active: bool | None = None


class StaffUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=2, max_length=100)
    active: bool | None = None


class HoursUpdate(BaseModel):
    opens_at: time | None = None
    closes_at: time | None = None
    closed: bool = False
