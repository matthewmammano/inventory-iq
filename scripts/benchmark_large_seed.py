"""Benchmark key routes and jobs against the separate large SQLite stress seed."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

DEFAULT_SEED_DB = Path("tmp/seed/2026-05-28_showcase_full.db")
DEFAULT_OUTPUT_JSON = Path("tmp/large_seed_benchmark.json")
DEVICE_COOKIE_VALUE = "benchmark-device"


@dataclass(frozen=True)
class BenchmarkSeedConfig:
    """CLI-facing mirror of the stress seed volume settings."""

    item_count: int = 500
    location_count: int = 8
    storages_per_location: int = 5
    count_cycles: int = 6
    count_spacing_days: int = 28
    chunk_size: int = 5000


@dataclass(frozen=True)
class BenchmarkContext:
    """Resolved IDs and URLs needed for realistic route benchmarks."""

    agency_id: int
    squad: str
    squad_url: str
    item_id: int
    location_id: int
    from_storage_id: int
    transfer_to_storage_id: int


class SqlCounter:
    """Count SQL statements executed on the active SQLAlchemy engine."""

    def __init__(self, engine) -> None:
        self.engine = engine
        self.count = 0

    def __enter__(self) -> SqlCounter:
        from sqlalchemy import event

        event.listen(self.engine, "before_cursor_execute", self._before_cursor_execute)
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        from sqlalchemy import event

        event.remove(self.engine, "before_cursor_execute", self._before_cursor_execute)

    def _before_cursor_execute(self, *args, **kwargs) -> None:
        self.count += 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Benchmark key routes/jobs against the large local stress seed.")
    parser.add_argument("--seed-db", type=Path, default=DEFAULT_SEED_DB, help="Large stress SQLite database file")
    parser.add_argument("--output-json", type=Path, default=DEFAULT_OUTPUT_JSON, help="Where to write the benchmark summary JSON")
    parser.add_argument("--rebuild-seed", action="store_true", help="Rebuild the stress seed before benchmarking")
    parser.add_argument("--items", type=int, default=BenchmarkSeedConfig.item_count, help="Items in the stress seed")
    parser.add_argument("--locations", type=int, default=BenchmarkSeedConfig.location_count, help="Locations in the stress seed")
    parser.add_argument("--storages", type=int, default=BenchmarkSeedConfig.storages_per_location, help="Storages per location in the stress seed")
    parser.add_argument("--count-cycles", type=int, default=BenchmarkSeedConfig.count_cycles, help="Historical full-count cycles per item/location")
    parser.add_argument("--count-spacing-days", type=int, default=BenchmarkSeedConfig.count_spacing_days, help="Days between historical count cycles")
    parser.add_argument("--chunk-size", type=int, default=BenchmarkSeedConfig.chunk_size, help="Bulk insert chunk size for seed generation")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    seed_config = BenchmarkSeedConfig(
        item_count=args.items,
        location_count=args.locations,
        storages_per_location=args.storages,
        count_cycles=args.count_cycles,
        count_spacing_days=args.count_spacing_days,
        chunk_size=args.chunk_size,
    )
    _configure_env(args.seed_db)
    seed_summary = _ensure_seed(args.seed_db, seed_config, rebuild=args.rebuild_seed)

    from sqlalchemy import func, or_, select

    import app.shared.database as dbmod
    from app import create_app
    from app.alerts.alert_service import generate_scheduled_alerts
    from app.auth.device_locations import DEVICE_COOKIE
    from app.auth.models import AgencyStorages
    from app.auth.queries import list_top_locations
    from app.inventory.location_operations import build_location_count_rows
    from app.inventory.models import ActionLogs
    from app.inventory.search_payload import load_item_search_payload
    from app.prediction.bulk_service import BulkService
    from app.shared.database import get_session

    app = create_app()
    app.config.update(TESTING=True)
    context = _load_context()

    with app.test_client() as client:
        _authenticate_client(client, context)
        _enable_admin_session(client)
        _save_device_location_for_guest_flow(context)
        client.set_cookie(DEVICE_COOKIE, DEVICE_COOKIE_VALUE)

        route_specs = [
            ("guest_index", "GET", f"/inventory/{context.squad_url}/", False),
            ("guest_scan_storages", "GET", f"/inventory/{context.squad_url}/scan/storages?item_id={context.item_id}", False),
            (
                "guest_scan_item_takeout",
                "GET",
                f"/inventory/{context.squad_url}/scan/item?item_id={context.item_id}&from_location_id={context.from_storage_id}&to_location_id=-1",
                False,
            ),
            ("admin_panel", "GET", f"/inventory/{context.squad_url}/admin-panel", True),
            ("admin_views", "GET", f"/inventory/{context.squad_url}/admin-panel/views", True),
            (
                "admin_scan_items",
                "GET",
                f"/inventory/{context.squad_url}/admin-panel/scan-items?from_location_id={context.from_storage_id}&to_location_id=-1",
                True,
            ),
            ("admin_history", "GET", f"/inventory/{context.squad_url}/admin-panel/history", True),
            ("admin_inventory_counts", "GET", f"/inventory/{context.squad_url}/admin-panel/inventory-count-levels", True),
            ("admin_restock", "GET", f"/inventory/{context.squad_url}/admin-panel/restock", True),
            (
                "admin_bulk_edit",
                "GET",
                f"/inventory/{context.squad_url}/admin-panel/bulk-actions/{context.location_id}/edit",
                True,
            ),
        ]
        route_results = [_run_route_benchmark(client, dbmod._engine, *spec) for spec in route_specs]

    service_results = []
    with get_session() as session:
        service_results.append(
            _run_callable_benchmark(
                dbmod._engine,
                "service_build_location_count_rows",
                lambda: _service_inventory_counts(session, context.location_id, build_location_count_rows),
            )
        )
        service_results.append(
            _run_callable_benchmark(
                dbmod._engine,
                "service_restock_analysis",
                lambda: _service_restock_rows(session, context.location_id, BulkService),
            )
        )
        service_results.append(
            _run_callable_benchmark(
                dbmod._engine,
                "service_history_all_logs",
                lambda: _service_history_logs(session, context, ActionLogs, or_, select, AgencyStorages),
            )
        )

    with get_session() as session:
        alert_result = _run_callable_benchmark(
            dbmod._engine,
            "job_generate_scheduled_alerts",
            lambda: generate_scheduled_alerts(session, agency_id=_agency_id(session)),
        )
        session.rollback()

    with get_session() as session:
        location_rows = {
            location.name: _count_location_logs(session, location.id, ActionLogs, AgencyStorages, func, or_, select)
            for location in list_top_locations(_agency_id(session), session=session)
        }
        guest_payload = _guest_payload_metrics(session, load_item_search_payload)

    query_plans = _query_plans(args.seed_db, context)
    output = {
        "generated_at": datetime.now(UTC).isoformat(),
        "seed": seed_summary,
        "routes": route_results,
        "services": service_results,
        "jobs": [alert_result],
        "history_rows": location_rows,
        "guest_payload": guest_payload,
        "query_plans": query_plans,
    }
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(output, indent=2))
    print(json.dumps(output, indent=2))


def _ensure_seed(seed_db: Path, config: BenchmarkSeedConfig, *, rebuild: bool) -> dict[str, Any]:
    seed_db = seed_db.resolve()
    if rebuild or not seed_db.exists():
        from scripts.setup_large_test_data import StressSeedConfig, build_large_seed

        started = time.perf_counter()
        summary = build_large_seed(
            seed_db,
            StressSeedConfig(
                item_count=config.item_count,
                location_count=config.location_count,
                storages_per_location=config.storages_per_location,
                count_cycles=config.count_cycles,
                count_spacing_days=config.count_spacing_days,
                chunk_size=config.chunk_size,
            ),
        )
        summary["build_ms"] = round((time.perf_counter() - started) * 1000, 1)
        return summary
    metadata = _read_seed_metadata(seed_db)
    if metadata is not None:
        metadata["build_ms"] = None
        return metadata
    return {
        "output_path": str(seed_db),
        "config": asdict(config),
        "counts": _sqlite_counts(seed_db),
        "build_ms": None,
    }


def _configure_env(seed_db: Path) -> None:
    os.environ["APP_ENV"] = "dev"
    os.environ["DATABASE_URL"] = f"sqlite:///{seed_db.resolve().as_posix()}"
    os.environ.setdefault("SECRET_KEY", "dev-secret-key")
    os.environ.setdefault("EMAIL_API_URL", "http://example.invalid")
    os.environ.setdefault("EMAIL_API_KEY", "dev-email-key")
    os.environ.setdefault("EMAIL_SENDER_EMAIL", "dev@example.com")
    os.environ.setdefault("CONTACT_PHONE", "")
    os.environ["SCHEDULER_ENABLED"] = "false"


def _load_context() -> BenchmarkContext:
    from sqlalchemy import select

    from app.auth.models import Agencies
    from app.inventory.models import Items
    from app.shared.database import get_session

    with get_session() as session:
        agency = session.execute(select(Agencies).where(Agencies.active.is_(True)).order_by(Agencies.id)).scalars().first()
        if agency is None:
            raise RuntimeError("No active agency was found in the benchmark seed")
        location = sorted(agency.locations, key=lambda row: row.name)[0]
        storages = sorted(location.storages, key=lambda storage: storage.name)
        item_id = session.scalar(select(Items.id).where(Items.agency_id == agency.id).order_by(Items.id))
        if item_id is None or len(storages) < 2:
            raise RuntimeError("Stress benchmark context is incomplete")
        return BenchmarkContext(
            agency_id=agency.id,
            squad=agency.display_name,
            squad_url=quote(agency.display_name, safe=""),
            item_id=int(item_id),
            location_id=location.id,
            from_storage_id=storages[0].id,
            transfer_to_storage_id=storages[1].id,
        )


def _authenticate_client(client, context: BenchmarkContext) -> None:
    with client.session_transaction() as session:
        session["_user_id"] = str(context.agency_id)
        session["_fresh"] = True


def _enable_admin_session(client) -> None:
    with client.session_transaction() as session:
        session["admin"] = True
        session["admin_last_active"] = datetime.now(UTC).timestamp()


def _refresh_admin_session(client) -> None:
    with client.session_transaction() as session:
        session["admin"] = True
        session["admin_last_active"] = datetime.now(UTC).timestamp()


def _save_device_location_for_guest_flow(context: BenchmarkContext) -> None:
    from app.auth.device_locations import save_device_location
    from app.shared.database import get_session

    with get_session() as session:
        save_device_location(context.agency_id, DEVICE_COOKIE_VALUE, context.location_id, session)
        session.commit()


def _benchmark_request(
    client,
    engine,
    name: str,
    method: str,
    url: str,
    *,
    admin_session: bool = False,
) -> dict[str, Any]:
    if admin_session:
        _refresh_admin_session(client)
    with SqlCounter(engine) as counter:
        started = time.perf_counter()
        response = client.open(url, method=method, follow_redirects=False)
        elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
    return {
        "name": name,
        "kind": "route",
        "method": method,
        "url": url,
        "status_code": response.status_code,
        "sql_calls": counter.count,
        "elapsed_ms": elapsed_ms,
        "response_bytes": len(response.data),
    }


def _run_route_benchmark(client, engine, name: str, method: str, url: str, admin_session: bool) -> dict[str, Any]:
    print(f"Running route benchmark: {name}", flush=True)
    result = _benchmark_request(client, engine, name, method, url, admin_session=admin_session)
    print(f"Finished route benchmark: {name} in {result['elapsed_ms']} ms with {result['sql_calls']} SQL calls", flush=True)
    return result


def _benchmark_callable(engine, name: str, func) -> dict[str, Any]:
    with SqlCounter(engine) as counter:
        started = time.perf_counter()
        result = func()
        elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
    summary = {
        "name": name,
        "kind": "callable",
        "sql_calls": counter.count,
        "elapsed_ms": elapsed_ms,
    }
    if isinstance(result, dict):
        summary.update(result)
    else:
        summary["result"] = result
    return summary


def _run_callable_benchmark(engine, name: str, func) -> dict[str, Any]:
    print(f"Running callable benchmark: {name}", flush=True)
    result = _benchmark_callable(engine, name, func)
    print(f"Finished callable benchmark: {name} in {result['elapsed_ms']} ms with {result['sql_calls']} SQL calls", flush=True)
    return result


def _service_inventory_counts(session, location_id: int, build_location_count_rows) -> dict[str, Any]:
    items, storages, counts = build_location_count_rows(session, _agency_id(session), location_id)
    return {
        "item_count": len(items),
        "storage_count": len(storages),
        "count_cells": len(counts),
    }


def _service_restock_rows(session, location_id: int, bulk_service) -> dict[str, Any]:
    rows = bulk_service.get_restock_analysis(session, _agency_id(session), location_id)
    return {"row_count": len(rows)}


def _service_history_logs(session, context: BenchmarkContext, action_logs, or_, select, agency_storages) -> dict[str, Any]:
    agency_id = _agency_id(session)
    storage_ids = [
        row[0]
        for row in session.execute(
            select(agency_storages.id).where(agency_storages.agency_id == agency_id, agency_storages.location_id == context.location_id)
        ).all()
    ]
    all_logs = list(session.execute(select(action_logs).where(action_logs.agency_id == agency_id).order_by(action_logs.id.desc())).scalars().all())
    location_logs = list(
        session.execute(
            select(action_logs)
            .where(
                action_logs.agency_id == agency_id,
                or_(action_logs.from_location_id.in_(storage_ids), action_logs.to_location_id.in_(storage_ids)),
            )
            .order_by(action_logs.id.desc())
        )
        .scalars()
        .all()
    )
    return {"all_log_rows": len(all_logs), "location_log_rows": len(location_logs)}


def _agency_id(session) -> int:
    from sqlalchemy import select

    from app.auth.models import Agencies
    from scripts.setup_large_test_data import STRESS_EMAIL

    agency_id = session.scalar(select(Agencies.id).where(Agencies.email == STRESS_EMAIL))
    if agency_id is None:
        agency_id = session.scalar(select(Agencies.id).where(Agencies.active.is_(True)).order_by(Agencies.id))
    if agency_id is None:
        raise RuntimeError("Benchmark agency id was not found")
    return int(agency_id)


def _guest_payload_metrics(session, load_item_search_payload) -> dict[str, Any]:
    payload = load_item_search_payload(
        session,
        _agency_id(session),
        order_by_last_accessed=True,
    )
    payload_json = json.dumps(payload)
    return {
        "item_count": len(payload),
        "payload_bytes": len(payload_json.encode()),
        "payload_kb": round(len(payload_json.encode()) / 1024, 1),
    }


def _count_location_logs(session, location_id: int, action_logs, agency_storages, func, or_, select) -> int:
    agency_id = _agency_id(session)
    storage_ids = [
        row[0]
        for row in session.execute(
            select(agency_storages.id).where(agency_storages.agency_id == agency_id, agency_storages.location_id == location_id)
        ).all()
    ]
    return int(
        session.scalar(
            select(func.count())
            .select_from(action_logs)
            .where(
                action_logs.agency_id == agency_id,
                or_(action_logs.from_location_id.in_(storage_ids), action_logs.to_location_id.in_(storage_ids)),
            )
        )
        or 0
    )


def _sqlite_counts(seed_db: Path) -> dict[str, int]:
    tables = (
        "agencies",
        "agency_emails",
        "agency_locations",
        "agency_storages",
        "agency_item_tags",
        "items",
        "action_logs",
        "inventory_trends",
    )
    with sqlite3.connect(seed_db) as connection:
        return {table: int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]) for table in tables}


def _read_seed_metadata(seed_db: Path) -> dict[str, Any] | None:
    metadata_path = seed_db.with_suffix(f"{seed_db.suffix}.meta.json")
    if not metadata_path.exists():
        return None
    return json.loads(metadata_path.read_text())


def _query_plans(seed_db: Path, context: BenchmarkContext) -> dict[str, list[str]]:
    plans = {
        "item_quantities": (
            "EXPLAIN QUERY PLAN "
            f"SELECT * FROM action_logs WHERE agency_id = {context.agency_id} AND item_id = {context.item_id} "
            "ORDER BY time_scanned ASC, id ASC"
        ),
        "history_all": f"EXPLAIN QUERY PLAN SELECT * FROM action_logs WHERE agency_id = {context.agency_id} ORDER BY id DESC",
        "history_location": (
            "EXPLAIN QUERY PLAN "
            f"SELECT * FROM action_logs WHERE agency_id = {context.agency_id} AND "
            f"(from_location_id IN ({context.from_storage_id},{context.transfer_to_storage_id}) "
            f"OR to_location_id IN ({context.from_storage_id},{context.transfer_to_storage_id})) "
            "ORDER BY id DESC"
        ),
        "restock_quantity_scan": (
            "EXPLAIN QUERY PLAN "
            "SELECT item_id, operation_type, from_location_id, to_location_id, quantity_delta "
            f"FROM action_logs WHERE agency_id = {context.agency_id} AND item_id IN ({context.item_id},{context.item_id + 1},{context.item_id + 2}) "
            f"AND (from_location_id IN ({context.from_storage_id},{context.transfer_to_storage_id}) "
            f"OR to_location_id IN ({context.from_storage_id},{context.transfer_to_storage_id})) "
            "ORDER BY time_scanned, id"
        ),
    }
    with sqlite3.connect(seed_db) as connection:
        return {name: [str(row[-1]) for row in connection.execute(sql).fetchall()] for name, sql in plans.items()}


if __name__ == "__main__":
    main()
