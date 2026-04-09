from __future__ import annotations

import os
from datetime import date, timedelta

import pytest
from sqlalchemy import create_engine, inspect, select
from sqlalchemy.orm import Session

from app.reports.smartrest_backend import run_smartrest_report
from app.schemas.reports import ReportFilters, ReportRequest, ReportType
from app.services.canonical_identity import CanonicalIdentityResolver
from app.smartrest.models import (
    CanonicalProfile,
    CanonicalSourceMap,
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
