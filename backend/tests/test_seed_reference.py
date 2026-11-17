"""Reference data and DB constraint smoke tests."""
from __future__ import annotations

from sqlalchemy import inspect, select, text

from app.models.catalog import Service, ServiceCategory
from app.models.identity import Permission, Role, RolePermission, User


def test_seed_created_no_users(client, db_session):
    assert db_session.execute(select(User)).scalars().all() == []


def test_roles_and_permission_matrix(db_session):
    roles = {r.code for r in db_session.execute(select(Role)).scalars()}
    assert roles == {
        "CUSTOMER", "INDEPENDENT_PROVIDER", "COMPANY_EMPLOYEE", "OPERATIONS_MANAGER",
        "CUSTOMER_SUPPORT_AGENT", "FINANCE_MANAGER", "SUPER_ADMIN",
    }
    super_admin = db_session.execute(select(Role).where(Role.code == "SUPER_ADMIN")).scalar_one()
    all_perms = db_session.execute(select(Permission)).scalars().all()
    granted = db_session.execute(
        select(RolePermission).where(RolePermission.role_id == super_admin.id)
    ).scalars().all()
    assert len(granted) == len(all_perms)

    customer = db_session.execute(select(Role).where(Role.code == "CUSTOMER")).scalar_one()
    customer_perms = {
        p.code
        for p in db_session.execute(
            select(Permission).join(RolePermission, RolePermission.permission_id == Permission.id).where(
                RolePermission.role_id == customer.id
            )
        ).scalars()
    }
    assert "booking:create" in customer_perms
    assert "admin:settings:manage" not in customer_perms
    assert "finance:settlements:manage" not in customer_perms


def test_catalogue_bilingual_data(db_session):
    categories = db_session.execute(select(ServiceCategory)).scalars().all()
    assert len(categories) == 10
    assert all(c.name_te and c.name_en for c in categories)
    services = db_session.execute(select(Service)).scalars().all()
    assert len(services) >= 38
    assert all(s.name_te and s.name_en for s in services)


def test_schema_has_expected_tables(engine):
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    for required in [
        "users", "roles", "permissions", "role_permissions", "user_roles", "customer_profiles",
        "provider_profiles", "employee_profiles", "provider_documents", "employee_attendance",
        "service_categories", "services", "service_pricing", "villages", "service_zones",
        "provider_skills", "provider_service_areas", "provider_availability",
        "customer_addresses", "customer_preferences",
        "bookings", "booking_items", "booking_assignments", "booking_status_history",
        "quotations", "quotation_items", "job_evidence", "job_time_logs",
        "payment_methods", "payments", "payment_webhook_events", "invoices", "invoice_items",
        "commissions", "provider_settlements", "settlement_items", "employee_compensation",
        "refunds", "financial_ledger", "reviews", "complaints", "dispute_messages",
        "support_tickets", "notifications", "notification_preferences", "message_templates",
        "system_settings", "audit_logs", "feature_flags", "content_pages",
    ]:
        assert required in tables, f"missing table {required}"


def test_active_assignment_unique_index_enforced(db_session):
    """The partial unique index prevents two active assignments on one booking."""
    idx = db_session.execute(
        text("SELECT indexdef FROM pg_indexes WHERE indexname = 'uq_active_assignment_per_booking'")
    ).scalar_one()
    assert "UNIQUE" in idx and "OFFERED" in idx
