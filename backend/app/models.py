from datetime import datetime, time, timezone
from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, Float, String, Text, Time, UniqueConstraint, JSON
from sqlalchemy.orm import Mapped, mapped_column
from .database import Base


class Organization(Base):
    """Group of branches owned by one organization. A null business.organization_id
    keeps existing independent businesses isolated by default.
    """
    __tablename__ = "organizations"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    slug: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class Business(Base):
    __tablename__ = "businesses"
    __table_args__ = (CheckConstraint("default_buffer_minutes >= 0", name="ck_business_buffer_nonnegative"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int | None] = mapped_column(ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True, index=True)
    demo_key: Mapped[str | None] = mapped_column(String(32), unique=True, nullable=True)
    name: Mapped[str] = mapped_column(String(120))
    category: Mapped[str] = mapped_column(String(32), default="salon", index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Kolkata")
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    default_buffer_minutes: Mapped[int] = mapped_column(Integer, default=0)
    check_in_minutes: Mapped[int] = mapped_column(Integer, default=30)
    early_arrival_minutes: Mapped[int] = mapped_column(Integer, default=30)
    queue_grace_minutes: Mapped[int] = mapped_column(Integer, default=10)
    queue_shift_minutes: Mapped[int] = mapped_column(Integer, default=15)
    cancellation_cutoff_hours: Mapped[int] = mapped_column(Integer, default=2)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))


class BusinessHours(Base):
    __tablename__ = "business_hours"
    __table_args__ = (UniqueConstraint("business_id", "weekday", name="uq_business_hours_day"), CheckConstraint("weekday >= 0 AND weekday <= 6", name="ck_business_hours_weekday"))
    id: Mapped[int] = mapped_column(primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id", ondelete="CASCADE"), index=True)
    weekday: Mapped[int] = mapped_column(Integer)
    opens_at: Mapped[time] = mapped_column(Time)
    closes_at: Mapped[time] = mapped_column(Time)


class Service(Base):
    __tablename__ = "services"
    __table_args__ = (CheckConstraint("duration_minutes > 0 AND duration_minutes <= 480", name="ck_service_duration"), CheckConstraint("buffer_minutes >= 0", name="ck_service_buffer"))
    id: Mapped[int] = mapped_column(primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text, default="")
    duration_minutes: Mapped[int] = mapped_column(Integer)
    buffer_minutes: Mapped[int] = mapped_column(Integer, default=0)
    price: Mapped[int | None] = mapped_column(Integer, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)


class Staff(Base):
    __tablename__ = "staff"
    id: Mapped[int] = mapped_column(primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    title: Mapped[str] = mapped_column(String(100), default="Team member")
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)


class StaffService(Base):
    __tablename__ = "staff_services"
    staff_id: Mapped[int] = mapped_column(ForeignKey("staff.id", ondelete="CASCADE"), primary_key=True)
    service_id: Mapped[int] = mapped_column(ForeignKey("services.id", ondelete="CASCADE"), primary_key=True)


class Availability(Base):
    __tablename__ = "availability"
    __table_args__ = (UniqueConstraint("business_id", "staff_id", "weekday", name="uq_staff_availability_day"), CheckConstraint("weekday >= 0 AND weekday <= 6", name="ck_staff_availability_weekday"))
    id: Mapped[int] = mapped_column(primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id", ondelete="CASCADE"), index=True)
    staff_id: Mapped[int] = mapped_column(ForeignKey("staff.id", ondelete="CASCADE"), index=True)
    weekday: Mapped[int] = mapped_column(Integer)
    start_time: Mapped[time] = mapped_column(Time)
    end_time: Mapped[time] = mapped_column(Time)


class StaffAbsence(Base):
    """Explicit time window for breaks, leave, and unavailability.

    Existing confirmed appointments are never moved automatically when one is entered.
    """
    __tablename__ = "staff_absences"
    __table_args__ = (
        CheckConstraint("ends_at > starts_at", name="ck_staff_absence_time_order"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id", ondelete="CASCADE"), index=True)
    staff_id: Mapped[int] = mapped_column(ForeignKey("staff.id", ondelete="CASCADE"), index=True)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    reason: Mapped[str] = mapped_column(String(24), default="break")
    source: Mapped[str] = mapped_column(String(24), default="admin")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class Appointment(Base):
    __tablename__ = "appointments"
    __table_args__ = (UniqueConstraint("business_id", "reference", name="uq_appointment_reference"), CheckConstraint("ends_at > starts_at", name="ck_appointment_time_order"), CheckConstraint("duration_minutes > 0", name="ck_appointment_duration"))
    id: Mapped[int] = mapped_column(primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id"), index=True)
    service_id: Mapped[int] = mapped_column(ForeignKey("services.id"))
    staff_id: Mapped[int] = mapped_column(ForeignKey("staff.id"), index=True)
    customer_email: Mapped[str] = mapped_column(String(255), index=True)
    customer_name: Mapped[str] = mapped_column(String(120))
    reference: Mapped[str] = mapped_column(String(16), index=True)
    qr_token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    duration_minutes: Mapped[int] = mapped_column(Integer, default=30)
    buffer_minutes: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(24), default="confirmed", index=True)
    checked_in_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class WaitlistEntry(Base):
    __tablename__ = "waitlist_entries"
    id: Mapped[int] = mapped_column(primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id"), index=True)
    service_id: Mapped[int] = mapped_column(ForeignKey("services.id"))
    customer_email: Mapped[str] = mapped_column(String(255))
    customer_name: Mapped[str] = mapped_column(String(120))
    preferred_date: Mapped[str] = mapped_column(String(10))
    status: Mapped[str] = mapped_column(String(24), default="waiting")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class SlotOffer(Base):
    __tablename__ = "slot_offers"
    id: Mapped[int] = mapped_column(primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id"), index=True)
    appointment_id: Mapped[int] = mapped_column(ForeignKey("appointments.id"))
    waitlist_entry_id: Mapped[int | None] = mapped_column(ForeignKey("waitlist_entries.id"), nullable=True)
    staff_id: Mapped[int] = mapped_column(ForeignKey("staff.id"))
    original_starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    original_ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    kind: Mapped[str] = mapped_column(String(24), default="queue_shift")
    status: Mapped[str] = mapped_column(String(24), default="pending")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Notification(Base):
    __tablename__ = "notifications"
    id: Mapped[int] = mapped_column(primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id"), index=True)
    customer_email: Mapped[str] = mapped_column(String(255), index=True)
    message: Mapped[str] = mapped_column(String(255))
    simulated: Mapped[bool] = mapped_column(Boolean, default=True)
    read: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class CustomerArrival(Base):
    __tablename__ = "customer_arrivals"
    __table_args__ = (CheckConstraint("eta_minutes IS NULL OR (eta_minutes >= 0 AND eta_minutes <= 180)", name="ck_arrival_eta"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    appointment_id: Mapped[int] = mapped_column(ForeignKey("appointments.id", ondelete="CASCADE"), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(24), default="on_the_way")
    eta_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class StaffPresence(Base):
    __tablename__ = "staff_presence"
    __table_args__ = (UniqueConstraint("business_id", "staff_id", name="uq_presence_business_staff"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id", ondelete="CASCADE"), index=True)
    staff_id: Mapped[int] = mapped_column(ForeignKey("staff.id", ondelete="CASCADE"))
    status: Mapped[str] = mapped_column(String(24), default="on_site")
    source: Mapped[str] = mapped_column(String(24), default="admin_demo")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class AdminAlert(Base):
    __tablename__ = "admin_alerts"
    id: Mapped[int] = mapped_column(primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id", ondelete="CASCADE"), index=True)
    message: Mapped[str] = mapped_column(String(255))
    kind: Mapped[str] = mapped_column(String(40), default="queue")
    reference: Mapped[str | None] = mapped_column(String(16), nullable=True)
    read: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class RecoveryPolicy(Base):
    """Advance authorization; existing bookings default to NO automatic changes."""
    __tablename__ = "recovery_policies"
    id: Mapped[int] = mapped_column(primary_key=True)
    appointment_id: Mapped[int] = mapped_column(ForeignKey("appointments.id", ondelete="CASCADE"), unique=True, index=True)
    allow_staff_substitution: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    allow_branch_transfer: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    max_delay_minutes: Mapped[int] = mapped_column(Integer, default=30, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    __table_args__ = (CheckConstraint("max_delay_minutes >= 0 AND max_delay_minutes <= 30", name="ck_recovery_max_delay"),)


class ServiceTransfer(Base):
    """Explicit, human-reviewed service equivalence across branches."""
    __tablename__ = "service_transfers"
    __table_args__ = (UniqueConstraint("source_service_id", "target_service_id", name="uq_service_transfer_pair"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    source_service_id: Mapped[int] = mapped_column(ForeignKey("services.id", ondelete="CASCADE"), index=True)
    target_service_id: Mapped[int] = mapped_column(ForeignKey("services.id", ondelete="CASCADE"), index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class RecoveryEvent(Base):
    __tablename__ = "recovery_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    appointment_id: Mapped[int] = mapped_column(ForeignKey("appointments.id"), index=True)
    from_business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id"))
    to_business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id"))
    from_service_id: Mapped[int] = mapped_column(ForeignKey("services.id"))
    to_service_id: Mapped[int] = mapped_column(ForeignKey("services.id"))
    from_staff_id: Mapped[int] = mapped_column(ForeignKey("staff.id"))
    to_staff_id: Mapped[int] = mapped_column(ForeignKey("staff.id"))
    previous_starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    new_starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    reason: Mapped[str] = mapped_column(String(48))
    actor: Mapped[str] = mapped_column(String(48), default="auto_engine")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class BookingHaircutPreference(Base):
    """One consultation record per booking. Remains attached through staff/branch transfers."""
    __tablename__ = "booking_haircut_preferences"
    __table_args__ = (
        CheckConstraint("length(notes) <= 800", name="ck_haircut_notes_length"),
        CheckConstraint("style IN ('fade', 'taper', 'trim', 'buzz_cut', 'layers', 'styling', 'other', 'not_sure')", name="ck_haircut_style"),
        CheckConstraint("preferred_length IN ('short', 'medium', 'long', 'unsure')", name="ck_haircut_length"),
    )
    appointment_id: Mapped[int] = mapped_column(ForeignKey("appointments.id", ondelete="CASCADE"), primary_key=True)
    style: Mapped[str] = mapped_column(String(32), default="not_sure", nullable=False)
    preferred_length: Mapped[str] = mapped_column(String(16), default="unsure", nullable=False)
    notes: Mapped[str] = mapped_column(Text, default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)


class BookingServiceIntake(Base):
    """Optional, category-specific appointment request that survives recovery moves.

    Personal details remain restricted to booking owners and branch admins.
    The appointment ID, rather than staff/branch ID, remains stable on reroute.
    """
    __tablename__ = "booking_service_intakes"
    __table_args__ = (
        CheckConstraint("length(summary) <= 160", name="ck_service_intake_summary_length"),
        CheckConstraint("length(notes) <= 1200", name="ck_service_intake_notes_length"),
    )
    appointment_id: Mapped[int] = mapped_column(ForeignKey("appointments.id", ondelete="CASCADE"), primary_key=True)
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    summary: Mapped[str] = mapped_column(String(160), default="", nullable=False)
    notes: Mapped[str] = mapped_column(Text, default="", nullable=False)
    answers: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)


class UserAccount(Base):
    __tablename__ = "user_accounts"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    password_salt: Mapped[str] = mapped_column(String(64), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    auth_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)


class AccountBusinessRole(Base):
    __tablename__ = "account_business_roles"
    __table_args__ = (UniqueConstraint("account_id", "business_id", "role", name="uq_account_business_role"),
                      CheckConstraint("role IN ('customer', 'admin', 'employee')", name="ck_account_role_allowed"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("user_accounts.id", ondelete="CASCADE"), nullable=False, index=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(24), nullable=False)
    staff_id: Mapped[int | None] = mapped_column(ForeignKey("staff.id", ondelete="SET NULL"), nullable=True)


class NotificationDelivery(Base):
    __tablename__ = "notification_deliveries"
    id: Mapped[int] = mapped_column(primary_key=True)
    notification_id: Mapped[int] = mapped_column(ForeignKey("notifications.id", ondelete="CASCADE"), nullable=False, unique=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="pending")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(String(200), nullable=True)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
