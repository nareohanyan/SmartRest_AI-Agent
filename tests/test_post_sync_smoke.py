from __future__ import annotations

import os
from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, inspect, select
from sqlalchemy.orm import Session

from app.agent.tools.business_insights import (
    fetch_customer_summary_tool,
    fetch_item_performance_tool,
    fetch_receipt_summary_tool,
)
from app.agent.tools.retrieval import fetch_breakdown_tool, fetch_total_metric_tool
from app.core.config import get_settings
from app.reports.smartrest_backend import run_smartrest_report
from app.schemas.analysis import (
    BreakdownRequest,
    CustomerSummaryRequest,
    DimensionName,
    ItemPerformanceMetric,
    ItemPerformanceRequest,
    MetricName,
    RankingMode,
    ReceiptSummaryRequest,
    RetrievalScope,
    TotalMetricRequest,
)
from app.schemas.reports import ReportFilters, ReportRequest, ReportType
from app.services.canonical_identity import CanonicalIdentityResolver
from app.smartrest.models import (
    CanonicalProfile,
    CanonicalSourceMap,
    Order,
    Profile,
    ProfileSourceMap,
    SourceSystem,
)

pytestmark = pytest.mark.post_sync

_REQUIRED_OPERATIONAL_TABLES = {
    "profiles",
    "users",
    "orders",
    "source_systems",
    "canonical_profiles",
    "profile_source_maps",
    "canonical_source_maps",
}


def _operational_database_url() -> str:
    db_url = os.getenv("SMARTREST_DATABASE_URL") or os.getenv("DATABASE_URL")
    if not db_url:
        raise pytest.UsageError(
            "Post-sync smoke tests require SMARTREST_DATABASE_URL or DATABASE_URL."
        )
    return db_url


@pytest.fixture(scope="session")
def operational_engine():
    db_url = _operational_database_url()
    engine = create_engine(db_url, future=True)
    try:
        with engine.connect() as connection:
            connection.execute(select(1))
    except Exception as exc:
        engine.dispose()
        raise pytest.UsageError(
            "Post-sync smoke tests require a reachable local SmartRest/Postgres database. "
            f"Connection error: {exc}"
        ) from exc

    try:
        yield engine
    finally:
        engine.dispose()


def test_post_sync_required_operational_tables_exist(operational_engine) -> None:
    inspector = inspect(operational_engine)
    available_tables = set(inspector.get_table_names())

    missing_tables = sorted(_REQUIRED_OPERATIONAL_TABLES - available_tables)
    assert not missing_tables, f"Missing required operational tables: {', '.join(missing_tables)}"


def test_post_sync_core_identity_tables_are_non_empty(operational_engine) -> None:
    with Session(bind=operational_engine) as session:
        profile_count = session.query(Profile).count()
        source_system_count = session.query(SourceSystem).count()
        canonical_profile_count = session.query(CanonicalProfile).count()
        profile_source_map_count = session.query(ProfileSourceMap).count()
        canonical_source_map_count = session.query(CanonicalSourceMap).count()

    assert profile_count > 0, "Expected synced profiles to exist in local SmartRest DB."
    assert source_system_count > 0, "Expected source systems to exist after identity sync."
    assert canonical_profile_count > 0, "Expected canonical profiles to exist after identity sync."
    assert (
        profile_source_map_count > 0
    ), "Expected profile source maps to exist after identity sync."
    assert (
        canonical_source_map_count > 0
    ), "Expected canonical user mappings to exist after identity sync."


def test_post_sync_canonical_identity_resolution_works_for_one_synced_mapping(
    operational_engine,
) -> None:
    with Session(bind=operational_engine) as session:
        mapping = session.execute(
            select(
                CanonicalSourceMap.profile_id,
                CanonicalSourceMap.user_id,
                SourceSystem.server_name,
                SourceSystem.cloud_num,
            )
            .join(SourceSystem, SourceSystem.id == CanonicalSourceMap.source_system_id)
            .limit(1)
        ).one_or_none()

        assert mapping is not None, "Expected at least one canonical source mapping after sync."

        profile = session.get(Profile, int(mapping.profile_id))
        assert profile is not None, "Expected mapped profile row to exist in local SmartRest DB."
        assert profile.profile_nick, "Expected mapped profile to have a profile_nick."
        profile_nick = str(profile.profile_nick)

    resolver = CanonicalIdentityResolver()
    resolution = resolver.resolve(
        user_id=int(mapping.user_id),
        profile_id=int(mapping.profile_id),
        profile_nick=profile_nick,
        source_server_name=str(mapping.server_name),
        source_cloud_num=int(mapping.cloud_num),
    )

    assert (
        resolution is not None
    ), "Expected canonical identity resolver to resolve a synced mapping."


def test_post_sync_live_report_backend_executes_for_one_synced_profile(
    operational_engine,
) -> None:
    with Session(bind=operational_engine) as session:
        profile_id = session.execute(select(Profile.id).limit(1)).scalar_one_or_none()

    assert profile_id is not None, "Expected at least one synced profile for report execution."

    today = date.today()
    request = ReportRequest(
        report_id=ReportType.SALES_TOTAL,
        filters=ReportFilters(
            date_from=today - timedelta(days=6),
            date_to=today,
        ),
    )
    response = run_smartrest_report(request, profile_id=int(profile_id))

    assert response.result.report_id is ReportType.SALES_TOTAL
    assert response.result.metrics


def test_post_sync_live_sales_by_source_report_executes_for_one_synced_profile(
    operational_engine,
) -> None:
    with Session(bind=operational_engine) as session:
        row = session.execute(
            select(Order.profile_id, Order.order_create_date)
            .where(Order.order_create_date.is_not(None))
            .order_by(Order.order_create_date.desc())
            .limit(1)
        ).one()

    date_to = row.order_create_date.date()
    date_from = date_to - timedelta(days=29)
    response = run_smartrest_report(
        ReportRequest(
            report_id=ReportType.SALES_BY_SOURCE,
            filters=ReportFilters(date_from=date_from, date_to=date_to),
        ),
        profile_id=int(row.profile_id),
    )

    metrics = {metric.label: metric.value for metric in response.result.metrics}
    assert set(metrics) == {"in_store", "takeaway"}
    assert sum(metrics.values()) >= 0


def test_post_sync_live_business_tools_execute_for_one_synced_profile(
    operational_engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with Session(bind=operational_engine) as session:
        row = session.execute(
            select(Order.profile_id, Order.order_create_date)
            .where(Order.order_create_date.is_not(None))
            .order_by(Order.order_create_date.desc())
            .limit(1)
        ).one()

    date_to = row.order_create_date.date()
    date_from = date_to - timedelta(days=29)
    scope = RetrievalScope(profile_id=int(row.profile_id))

    monkeypatch.setenv("SMARTREST_ANALYTICS_BACKEND_MODE", "db_strict")
    get_settings.cache_clear()

    item_response = fetch_item_performance_tool(
        ItemPerformanceRequest(
            metric=ItemPerformanceMetric.ITEM_REVENUE,
            date_from=date_from,
            date_to=date_to,
            ranking_mode=RankingMode.TOP_K,
            limit=5,
            scope=scope,
        )
    )
    customer_response = fetch_customer_summary_tool(
        CustomerSummaryRequest(date_from=date_from, date_to=date_to, scope=scope)
    )
    receipt_response = fetch_receipt_summary_tool(
        ReceiptSummaryRequest(date_from=date_from, date_to=date_to, scope=scope)
    )

    assert item_response.items
    assert customer_response.total_order_count >= customer_response.identified_order_count
    assert receipt_response.receipt_count >= receipt_response.linked_order_count
    get_settings.cache_clear()


def test_post_sync_live_breakdown_tools_execute_for_payment_method_and_category(
    operational_engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with Session(bind=operational_engine) as session:
        row = session.execute(
            select(Order.profile_id, Order.order_create_date)
            .where(Order.order_create_date.is_not(None))
            .order_by(Order.order_create_date.desc())
            .limit(1)
        ).one()

    date_to = row.order_create_date.date()
    date_from = date_to - timedelta(days=29)
    scope = RetrievalScope(profile_id=int(row.profile_id))

    monkeypatch.setenv("SMARTREST_ANALYTICS_BACKEND_MODE", "db_strict")
    get_settings.cache_clear()

    payment_response = fetch_breakdown_tool(
        BreakdownRequest(
            metric=MetricName.SALES_TOTAL,
            dimension=DimensionName.PAYMENT_METHOD,
            date_from=date_from,
            date_to=date_to,
            scope=scope,
        )
    )
    category_response = fetch_breakdown_tool(
        BreakdownRequest(
            metric=MetricName.SALES_TOTAL,
            dimension=DimensionName.CATEGORY,
            date_from=date_from,
            date_to=date_to,
            scope=scope,
        )
    )

    assert payment_response.items
    assert any(item.label in {"cash", "card", "idram"} for item in payment_response.items)
    assert (
        sum((item.value for item in payment_response.items), Decimal("0"))
        == payment_response.total_value
    )

    assert category_response.items
    assert all(item.label.strip() for item in category_response.items)
    assert (
        sum((item.value for item in category_response.items), Decimal("0"))
        == category_response.total_value
    )
    get_settings.cache_clear()


def test_post_sync_live_total_tools_execute_for_new_metrics(
    operational_engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with Session(bind=operational_engine) as session:
        row = session.execute(
            select(Order.profile_id, Order.order_create_date)
            .where(Order.order_create_date.is_not(None))
            .order_by(Order.order_create_date.desc())
            .limit(1)
        ).one()

    date_to = row.order_create_date.date()
    date_from = date_to - timedelta(days=29)
    scope = RetrievalScope(profile_id=int(row.profile_id))

    monkeypatch.setenv("SMARTREST_ANALYTICS_BACKEND_MODE", "db_strict")
    get_settings.cache_clear()

    quantity_response = fetch_total_metric_tool(
        TotalMetricRequest(
            metric=MetricName.QUANTITY_SOLD,
            date_from=date_from,
            date_to=date_to,
            scope=scope,
        )
    )
    gross_sales_response = fetch_total_metric_tool(
        TotalMetricRequest(
            metric=MetricName.GROSS_SALES_TOTAL,
            date_from=date_from,
            date_to=date_to,
            scope=scope,
        )
    )
    sales_total_response = fetch_total_metric_tool(
        TotalMetricRequest(
            metric=MetricName.SALES_TOTAL,
            date_from=date_from,
            date_to=date_to,
            scope=scope,
        )
    )
    items_per_order_response = fetch_total_metric_tool(
        TotalMetricRequest(
            metric=MetricName.ITEMS_PER_ORDER,
            date_from=date_from,
            date_to=date_to,
            scope=scope,
        )
    )

    assert quantity_response.value >= 0
    assert gross_sales_response.value >= 0
    assert gross_sales_response.value >= sales_total_response.value
    assert items_per_order_response.value >= 0
    get_settings.cache_clear()
