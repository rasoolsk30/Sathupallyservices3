"""Reference data seeding — NON-PRODUCTION reference data only.

Seeds: permissions, roles, role→permission map, payment methods, feature flags,
system settings, content pages (draft), message templates, service catalogue with
Telugu names, and the Sathupally village placeholder.

Idempotent: safe to run repeatedly. Creates NO users, NO providers, NO bookings,
NO payments, NO reviews. Real accounts are created by the owner via
`python -m scripts.create_admin` and the provider/customer registration flows.
"""
from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import SessionLocal
from app.models.admin import ContentPage, FeatureFlag, SystemSetting
from app.models.catalog import Service, ServiceCategory, ServicePricing, Village
from app.models.communication import MessageTemplate
from app.models.enums import PriceType, RoleCode
from app.models.finance import PaymentMethod
from app.models.identity import Permission, Role, RolePermission

log = logging.getLogger("ssh.seed")

# ---------------------------------------------------------------------------
# Permissions
# ---------------------------------------------------------------------------
PERMISSIONS: dict[str, str] = {
    # self / common
    "self:profile:read": "Read own profile",
    "self:profile:write": "Update own profile",
    "content:read": "Read published content pages",
    "notification:read:own": "Read own notifications",
    "support:ticket:create": "Create a support ticket",
    "complaint:create": "Raise a complaint",
    "complaint:read:own": "Read own complaints",
    # customer
    "customer:addresses:manage": "Manage own addresses",
    "service:catalog:read": "Browse the service catalogue",
    "booking:create": "Create bookings",
    "booking:read:own": "Read own bookings",
    "booking:cancel:own": "Cancel own bookings",
    "quotation:approve:own": "Approve/reject quotations for own bookings",
    "payment:pay:own": "Pay for own bookings",
    "review:create:own": "Review own completed bookings",
    # independent provider
    "provider:profile:read:own": "Read own provider profile",
    "provider:profile:write:own": "Update own provider profile",
    "provider:documents:submit": "Submit verification documents",
    "provider:skills:manage": "Manage own skills",
    "provider:areas:manage": "Manage own service areas",
    "provider:availability:manage": "Manage own availability",
    "provider:status:toggle": "Toggle own online/offline status",
    "provider:jobs:read:own": "Read own assigned jobs",
    "provider:jobs:respond": "Accept or reject offered jobs",
    "quotation:submit": "Submit quotations",
    "quotation:revise": "Revise own quotations",
    "job:status:update:own": "Update status of own jobs",
    "job:evidence:upload": "Upload job evidence",
    "provider:earnings:read:own": "Read own earnings and commission statements",
    # employee
    "employee:profile:read:own": "Read own employee profile",
    "employee:jobs:read:own": "Read own assigned jobs",
    "employee:jobs:accept": "Accept assigned work",
    "employee:attendance:self": "Mark own attendance",
    "employee:compensation:read:own": "Read own compensation records",
    # operations
    "ops:jobs:monitor": "Monitor active jobs",
    "ops:employees:coordinate": "Coordinate employees",
    "booking:read:all": "Read all bookings",
    "booking:assign": "Assign providers/employees to bookings",
    "complaint:read:all": "Read all complaints",
    "complaint:respond": "Respond to complaints",
    "customer:read:all": "Read customer records",
    # finance
    "finance:payments:read": "Read payments",
    "finance:payments:record": "Record direct/admin payments",
    "finance:refunds:manage": "Manage refunds",
    "finance:commissions:manage": "Manage commissions",
    "finance:settlements:manage": "Create and pay provider settlements",
    "finance:ledger:read": "Read the financial ledger",
    "finance:reports:read": "Read financial reports",
    "invoice:read:all": "Read all invoices",
    # admin
    "admin:dashboard:read": "View admin dashboard",
    "admin:users:read": "View users",
    "admin:users:manage": "Create/update/suspend users",
    "admin:customers:manage": "Manage customers",
    "admin:providers:read": "View providers",
    "admin:providers:verify": "Verify provider documents",
    "admin:providers:manage": "Create/update/suspend providers",
    "admin:employees:manage": "Manage employees and attendance",
    "admin:attendance:manage": "Manage employee attendance records",
    "admin:compensation:manage": "Manage employee compensation",
    "admin:roles:manage": "Manage roles and permissions",
    "admin:services:manage": "Manage categories and services",
    "admin:pricing:manage": "Manage pricing",
    "admin:villages:manage": "Manage villages and zones",
    "admin:bookings:manage": "Manage bookings",
    "admin:quotations:monitor": "Monitor quotations",
    "admin:jobs:monitor": "Monitor jobs",
    "admin:payments:manage": "Manage payments and reconciliation",
    "admin:commissions:manage": "Manage commission rules",
    "admin:settlements:manage": "Manage settlements",
    "admin:refunds:manage": "Manage refunds",
    "admin:complaints:manage": "Manage complaints and disputes",
    "admin:reviews:moderate": "Moderate reviews",
    "admin:promotions:manage": "Manage promotions",
    "admin:notifications:manage": "Send/manage notifications",
    "admin:support:manage": "Manage support tickets",
    "admin:reports:read": "Read business reports",
    "admin:analytics:read": "Read analytics",
    "admin:tax:read": "Read tax reports",
    "admin:content:manage": "Manage content pages",
    "admin:settings:manage": "Manage system settings",
    "admin:audit:read": "Read audit logs",
    "admin:security:read": "Read security events",
    "admin:backup:manage": "Manage backups",
    "admin:documents:manage": "Access private documents",
}

CUSTOMER_PERMS = [
    "self:profile:read", "self:profile:write", "content:read", "notification:read:own",
    "support:ticket:create", "complaint:create", "complaint:read:own",
    "customer:addresses:manage", "service:catalog:read",
    "booking:create", "booking:read:own", "booking:cancel:own",
    "quotation:approve:own", "payment:pay:own", "review:create:own",
]

PROVIDER_PERMS = [
    "self:profile:read", "self:profile:write", "content:read", "notification:read:own",
    "support:ticket:create", "complaint:create", "complaint:read:own", "service:catalog:read",
    "provider:profile:read:own", "provider:profile:write:own", "provider:documents:submit",
    "provider:skills:manage", "provider:areas:manage", "provider:availability:manage",
    "provider:status:toggle", "provider:jobs:read:own", "provider:jobs:respond",
    "quotation:submit", "quotation:revise", "job:status:update:own", "job:evidence:upload",
    "provider:earnings:read:own",
]

EMPLOYEE_PERMS = [
    "self:profile:read", "content:read", "notification:read:own",
    "employee:profile:read:own", "employee:jobs:read:own", "employee:jobs:accept",
    "job:status:update:own", "job:evidence:upload", "employee:attendance:self",
    "employee:compensation:read:own",
]

OPS_PERMS = [
    "self:profile:read", "content:read", "notification:read:own",
    "admin:dashboard:read", "ops:jobs:monitor", "ops:employees:coordinate",
    "booking:read:all", "booking:assign", "admin:jobs:monitor", "admin:quotations:monitor",
    "admin:bookings:manage", "complaint:read:all", "complaint:respond",
    "admin:employees:manage", "admin:attendance:manage", "admin:providers:read",
    "admin:employees:manage", "service:catalog:read",
]

SUPPORT_PERMS = [
    "self:profile:read", "content:read", "notification:read:own",
    "admin:dashboard:read", "support:ticket:create", "admin:support:manage",
    "complaint:read:all", "complaint:respond", "booking:read:all", "customer:read:all",
    "admin:notifications:manage", "admin:providers:read",
]

FINANCE_PERMS = [
    "self:profile:read", "content:read", "notification:read:own",
    "admin:dashboard:read", "booking:read:all",
    "finance:payments:read", "finance:payments:record", "finance:refunds:manage",
    "finance:commissions:manage", "finance:settlements:manage", "finance:ledger:read",
    "finance:reports:read", "invoice:read:all",
    "admin:payments:manage", "admin:refunds:manage", "admin:commissions:manage",
    "admin:settlements:manage", "admin:reports:read", "admin:tax:read", "admin:analytics:read",
]

ROLE_DEFS = {
    RoleCode.CUSTOMER: ("Customer", CUSTOMER_PERMS),
    RoleCode.INDEPENDENT_PROVIDER: ("Independent Provider", PROVIDER_PERMS),
    RoleCode.COMPANY_EMPLOYEE: ("Company Employee", EMPLOYEE_PERMS),
    RoleCode.OPERATIONS_MANAGER: ("Operations Manager", OPS_PERMS),
    RoleCode.CUSTOMER_SUPPORT_AGENT: ("Customer Support Agent", SUPPORT_PERMS),
    RoleCode.FINANCE_MANAGER: ("Finance Manager", FINANCE_PERMS),
    RoleCode.SUPER_ADMIN: ("Super Admin", ["*"]),
}

# ---------------------------------------------------------------------------
# Catalogue reference data (prices intentionally unset — owner configures)
# ---------------------------------------------------------------------------
CATALOGUE = [
    {
        "slug": "electrical", "name_en": "Electrical Services", "name_te": "విద్యుత్ సేవలు",
        "icon": "zap", "services": [
            ("electrical-fan", "Fan Installation & Repair", "ఫ్యాన్ అమర్చడం & మరమ్మతు", 60),
            ("electrical-lighting", "Lighting Repair", "విద్యుత్ లైట్ల మరమ్మతు", 45),
            ("electrical-switchboard", "Switchboard Repair", "స్విచ్‌బోర్డ్ మరమ్మతు", 45),
            ("electrical-wiring", "House Wiring", "ఇంటి వైరింగ్", 240),
            ("electrical-troubleshooting", "Electrical Troubleshooting", "విద్యుత్ సమస్య పరిష్కారం", 60),
        ],
    },
    {
        "slug": "plumbing", "name_en": "Plumbing", "name_te": "ప్లంబింగ్",
        "icon": "droplet", "services": [
            ("plumbing-tap", "Tap Repair", "కుళాయి మరమ్మతు", 30),
            ("plumbing-leak", "Pipe Leakage Repair", "పైపు లీకేజీ మరమ్మతు", 60),
            ("plumbing-bathroom", "Bathroom Plumbing", "బాత్‌రూమ్ ప్లంబింగ్", 120),
            ("plumbing-motor", "Water Motor Repair", "వాటర్ మోటార్ మరమ్మతు", 90),
            ("plumbing-drainage", "Drainage Troubleshooting", "డ్రైనేజీ సమస్య పరిష్కారం", 90),
        ],
    },
    {
        "slug": "ac-appliances", "name_en": "AC & Appliances", "name_te": "ఏసీ & గృహోపకరణాలు",
        "icon": "wind", "services": [
            ("appliance-ac-service", "AC Servicing", "ఏసీ సర్వీసింగ్", 90),
            ("appliance-ac-install", "AC Installation", "ఏసీ ఇన్‌స్టాలేషన్", 120),
            ("appliance-fridge", "Refrigerator Repair", "ఫ్రిజ్ మరమ్మతు", 90),
            ("appliance-washing", "Washing Machine Repair", "వాషింగ్ మెషీన్ మరమ్మతు", 90),
            ("appliance-troubleshoot", "Appliance Troubleshooting", "గృహోపకరణ సమస్య పరిష్కారం", 60),
        ],
    },
    {
        "slug": "vehicle", "name_en": "Vehicle Services", "name_te": "వాహన సేవలు",
        "icon": "truck", "services": [
            ("vehicle-bike-repair", "Bike Repair", "బైక్ మరమ్మతు", 90),
            ("vehicle-puncture", "Puncture Assistance", "పంక్చర్ సహాయం", 30),
            ("vehicle-battery", "Battery Assistance", "బ్యాటరీ సహాయం", 30),
            ("vehicle-servicing", "Basic Vehicle Servicing", "బేసిక్ వాహన సర్వీసింగ్", 120),
            ("vehicle-onsite-mechanic", "On-site Mechanic Assistance", "ఆన్-సైట్ మెకానిక్ సహాయం", 90),
        ],
    },
    {
        "slug": "home-cleaning", "name_en": "Home Cleaning", "name_te": "ఇంటి శుభ్రత",
        "icon": "sparkles", "services": [
            ("cleaning-deep", "Deep Home Cleaning", "ఇంటి డీప్ క్లీనింగ్", 240),
            ("cleaning-bathroom", "Bathroom Cleaning", "బాత్‌రూమ్ క్లీనింగ్", 60),
            ("cleaning-kitchen", "Kitchen Cleaning", "వంటగది క్లీనింగ్", 90),
            ("cleaning-sofa", "Sofa Cleaning", "సోఫా క్లీనింగ్", 90),
        ],
    },
    {
        "slug": "carpentry", "name_en": "Carpentry", "name_te": "వడ్రంగి పని",
        "icon": "hammer", "services": [
            ("carpentry-furniture", "Furniture Repair", "ఫర్నిచర్ మరమ్మతు", 120),
            ("carpentry-doors", "Door & Window Repair", "తలుపు & కిటికీ మరమ్మతు", 90),
            ("carpentry-custom", "Custom Carpentry Work", "కస్టమ్ వడ్రంగి పని", 240),
        ],
    },
    {
        "slug": "painting", "name_en": "Painting", "name_te": "పెయింటింగ్",
        "icon": "paintbrush", "services": [
            ("painting-interior", "Interior Painting", "ఇంటి లోపలి పెయింటింగ్", 480),
            ("painting-exterior", "Exterior Painting", "బయటి పెయింటింగ్", 480),
            ("painting-touchup", "Touch-up Painting", "టచ్-అప్ పెయింటింగ్", 120),
        ],
    },
    {
        "slug": "pest-control", "name_en": "Pest Control", "name_te": "పురుగుల నివారణ",
        "icon": "bug", "services": [
            ("pest-general", "General Pest Control", "సాధారణ పురుగుల నివారణ", 120),
            ("pest-termite", "Termite Treatment", "చెదలు నివారణ", 180),
            ("pest-mosquito", "Mosquito Control", "దోమల నివారణ", 60),
        ],
    },
    {
        "slug": "computer-electronics", "name_en": "Computer & Electronics Repair", "name_te": "కంప్యూటర్ & ఎలక్ట్రానిక్స్ మరమ్మతు",
        "icon": "laptop", "services": [
            ("computer-laptop", "Laptop Repair", "ల్యాప్‌టాప్ మరమ్మతు", 120),
            ("computer-desktop", "Desktop Repair", "డెస్క్‌టాప్ మరమ్మతు", 120),
            ("computer-printer", "Printer Repair", "ప్రింటర్ మరమ్మతు", 90),
            ("computer-cctv", "CCTV Installation", "సీసీటీవీ ఇన్‌స్టాలేషన్", 180),
        ],
    },
    {
        "slug": "other", "name_en": "Other Services", "name_te": "ఇతర సేవలు",
        "icon": "tool", "services": [
            ("other-handyman", "General Handyman Work", "జనరల్ హ్యాండీమ్యాన్ పని", 90),
        ],
    },
]

SAFETY_EN = "For electrical or gas work, keep the main switch/gas supply off and children away until the technician arrives."
SAFETY_TE = "విద్యుత్ లేదా గ్యాస్ పని అయితే, టెక్నీషియన్ వచ్చే వరకు మెయిన్ స్విచ్/గ్యాస్ ఆఫ్ చేసి పిల్లలను దూరంగా ఉంచండి."

PAYMENT_METHODS = [
    ("CASH_DIRECT", "Cash (pay provider directly)", "నగదు (ప్రొవైడర్‌కు నేరుగా)", "CASH"),
    ("UPI_DIRECT", "UPI (pay provider directly)", "యూపీఐ (ప్రొవైడర్‌కు నేరుగా)", "UPI"),
    ("PLATFORM_GATEWAY", "Pay online via platform", "ప్లాట్‌ఫారమ్ ద్వారా ఆన్‌లైన్ చెల్లింపు", "GATEWAY"),
    ("ADMIN_RECORDED_CASH", "Cash recorded by staff", "సిబ్బంది నమోదు చేసిన నగదు", "CASH"),
]

FEATURE_FLAGS = [
    ("payments.gateway", False, "Enable online payment gateway checkout (requires merchant onboarding)"),
    ("otp.login", False, "Enable SMS OTP verification (requires approved SMS provider)"),
    ("emergency.bookings", True, "Allow emergency booking requests"),
    ("guest.browsing", True, "Allow unauthenticated browsing of the service catalogue"),
    ("provider.self_registration", True, "Allow independent providers to self-register"),
]

SYSTEM_SETTINGS = [
    ("commission.default_bps", 1000, "Default independent-provider commission in basis points (10%)"),
    ("booking.max_advance_days", 30, "How many days ahead a booking can be scheduled"),
    ("booking.min_cancel_notice_hours", 2, "Free cancellation window before scheduled slot"),
    ("platform.support_phone", "", "Customer support phone shown in the app"),
    ("platform.support_whatsapp", "", "Click-to-chat WhatsApp support number (E.164 without +)"),
    ("platform.min_payout_paise", 0, "Minimum provider settlement amount in paise"),
    ("invoice.tax_note", "Taxes as applicable. GST registration pending.", "Invoice footer note"),
]

CONTENT_PAGES = [
    ("about", "About Sathupally Service Hub", "సత్తుపల్లి సర్వీస్ హబ్ గురించి",
     "Sathupally Service Hub connects households and businesses in Sathupally Mandal with verified local service providers. Draft copy — owner must review before publication.",
     "సత్తుపల్లి మండలంలోని ఇళ్లు మరియు వ్యాపారాలను ధృవీకరించిన స్థానిక సేవా ప్రొవైడర్లతో కలిపే వేదిక. డ్రాఫ్ట్ — ప్రచురణకు ముందు యజమాని సమీక్షించాలి."),
    ("terms", "Terms and Conditions", "నిబంధనలు మరియు షరతులు",
     "DRAFT — requires legal review before launch. Placeholder terms pending qualified legal counsel.",
     "డ్రాఫ్ట్ — ప్రారంభానికి ముందు చట్టపరమైన సమీక్ష అవసరం."),
    ("privacy", "Privacy Policy", "గోప్యతా విధానం",
     "DRAFT — requires legal review before launch. Describes what data is collected (account, address, booking, payment records) and how it is used. Placeholder pending qualified legal counsel.",
     "డ్రాఫ్ట్ — ప్రారంభానికి ముందు చట్టపరమైన సమీక్ష అవసరం."),
    ("help", "Help Centre", "సహాయ కేంద్రం",
     "For help, use in-app support or contact the support number configured by the operator.",
     "సహాయం కోసం యాప్‌లోని సపోర్ట్ లేదా ఆపరేటర్ ఇచ్చిన సపోర్ట్ నంబర్‌ను ఉపయోగించండి."),
]

TEMPLATES = [
    ("booking.created", "Your booking {booking_number} has been created."),
    ("booking.accepted", "Your booking {booking_number} has been accepted by the provider."),
    ("booking.rejected", "The provider could not accept booking {booking_number}. We are finding another option."),
    ("quotation.received", "A quotation was received for booking {booking_number}."),
    ("quotation.approved", "Quotation approved for booking {booking_number}."),
    ("job.assigned", "You have been assigned booking {booking_number}."),
    ("job.started", "Work has started for booking {booking_number}."),
    ("job.completed", "Work has been completed for booking {booking_number}. Please confirm."),
    ("payment.confirmed", "Payment confirmed for booking {booking_number}."),
    ("booking.cancelled", "Booking {booking_number} has been cancelled."),
    ("refund.processed", "Refund processed for booking {booking_number}."),
    ("complaint.updated", "Your complaint {complaint_number} has been updated."),
    ("verification.updated", "Your verification status has been updated."),
    ("settlement.paid", "Settlement {settlement_number} has been paid."),
]


def _get_or_create(db: Session, model, defaults: dict | None = None, **filters):
    obj = db.execute(select(model).filter_by(**filters)).scalars().first()
    if obj is None:
        obj = model(**filters, **(defaults or {}))
        db.add(obj)
        db.flush()
    return obj


def seed(db: Session) -> None:
    # Guard: every permission referenced by a role must exist in the catalogue.
    referenced = {p for _label, perms in ROLE_DEFS.values() for p in perms if p != "*"}
    undefined = referenced - set(PERMISSIONS)
    if undefined:
        raise RuntimeError(f"Seed configuration error — undefined permissions: {sorted(undefined)}")

    # 1. Permissions
    perm_objs: dict[str, Permission] = {}
    for code, desc in PERMISSIONS.items():
        perm_objs[code] = _get_or_create(db, Permission, {"description": desc}, code=code)

    # 2. Roles + mapping
    for role_code, (label, perms) in ROLE_DEFS.items():
        role = _get_or_create(db, Role, {"name": label, "is_system": True}, code=role_code.value)
        target = set(PERMISSIONS) if perms == ["*"] else set(perms)
        existing = {
            p for (p,) in db.execute(
                select(Permission.code)
                .join(RolePermission, RolePermission.permission_id == Permission.id)
                .where(RolePermission.role_id == role.id)
            )
        }
        for code in target - existing:
            db.add(RolePermission(role_id=role.id, permission_id=perm_objs[code].id))

    # 3. Payment methods
    for code, en, te, mtype in PAYMENT_METHODS:
        _get_or_create(db, PaymentMethod, {"name_en": en, "name_te": te, "method_type": mtype}, code=code)

    # 4. Feature flags
    for key, enabled, desc in FEATURE_FLAGS:
        _get_or_create(db, FeatureFlag, {"is_enabled": enabled, "description": desc}, key=key)

    # 5. System settings
    for key, value, desc in SYSTEM_SETTINGS:
        _get_or_create(db, SystemSetting, {"value": value, "description": desc}, key=key)

    # 6. Content pages
    for slug, title_en, title_te, body_en, body_te in CONTENT_PAGES:
        _get_or_create(
            db, ContentPage,
            {"title_en": title_en, "title_te": title_te, "body_en": body_en, "body_te": body_te, "is_published": True},
            slug=slug,
        )

    # 7. Message templates
    for code, body in TEMPLATES:
        _get_or_create(db, MessageTemplate, {"body_en": body, "channel": "IN_APP"}, code=code)

    # 8. Catalogue
    for order, cat in enumerate(CATALOGUE):
        category = _get_or_create(
            db, ServiceCategory,
            {"name_en": cat["name_en"], "name_te": cat["name_te"], "icon": cat["icon"], "display_order": order},
            slug=cat["slug"],
        )
        for s_order, (slug, en, te, duration) in enumerate(cat["services"]):
            service = _get_or_create(
                db, Service,
                {
                    "category_id": category.id,
                    "name_en": en,
                    "name_te": te,
                    "estimated_duration_minutes": duration,
                    "safety_instructions_en": SAFETY_EN,
                    "safety_instructions_te": SAFETY_TE,
                    "display_order": s_order,
                },
                slug=slug,
            )
            has_price = db.execute(select(ServicePricing.id).where(ServicePricing.service_id == service.id)).first()
            if not has_price:
                db.add(
                    ServicePricing(
                        service_id=service.id,
                        price_type=PriceType.QUOTE_ONLY,
                        base_price_paise=0,
                        inspection_fee_paise=0,
                        tax_rate_bps=0,
                        is_active=True,
                        notes="Reference row — owner must configure real pricing before pilot launch.",
                    )
                )

    # 9. Villages: only the mandal headquarters is pre-identified.
    #    Business rule: a village is only advertised as covered when an active provider serves it
    #    (enforced by the availability API). The owner adds remaining mandal villages from
    #    official mandal records in Admin → Villages.
    _get_or_create(
        db, Village,
        {"name_te": "సత్తుపల్లి", "mandal": "Sathupally", "district": "Khammam", "is_active": True,
         "notes": "Mandal headquarters. Verify remaining mandal villages against official records before adding."},
        name="Sathupally",
    )

    db.commit()
    log.info("Reference data seeded.")


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    with SessionLocal() as db:
        seed(db)


if __name__ == "__main__":
    main()
