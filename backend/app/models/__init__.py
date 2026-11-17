"""Import every model so Alembic autogenerate and relationship resolution see all tables."""
from app.models.base import Base  # noqa: F401
from app.models.identity import (  # noqa: F401
    AuthRefreshToken,
    CustomerProfile,
    EmployeeAttendance,
    EmployeeProfile,
    Permission,
    ProviderDocument,
    ProviderProfile,
    Role,
    RolePermission,
    User,
    UserRole,
)
from app.models.catalog import (  # noqa: F401
    ProviderAvailability,
    ProviderServiceArea,
    ProviderSkill,
    Service,
    ServiceCategory,
    ServicePricing,
    ServiceZone,
    Village,
)
from app.models.customer import CustomerAddress, CustomerPreference  # noqa: F401
from app.models.booking import (  # noqa: F401
    Booking,
    BookingAssignment,
    BookingItem,
    BookingStatusHistory,
    JobEvidence,
    JobTimeLog,
    Quotation,
    QuotationItem,
)
from app.models.finance import (  # noqa: F401
    Commission,
    EmployeeCompensation,
    FinancialLedger,
    Invoice,
    InvoiceItem,
    Payment,
    PaymentMethod,
    PaymentWebhookEvent,
    ProviderSettlement,
    Refund,
    SettlementItem,
)
from app.models.quality import Complaint, DisputeMessage, Review, SupportTicket  # noqa: F401
from app.models.communication import MessageTemplate, Notification, NotificationPreference  # noqa: F401
from app.models.admin import AuditLog, ContentPage, FeatureFlag, SystemSetting  # noqa: F401

__all__ = ["Base"]
