"""SQLite persistence layer with WAL mode and append-only audit records."""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from campaign_automaton.models import (
    ArtifactStatus,
    CampaignCloneRequest,
    CampaignCreate,
    CampaignStatus,
    CampaignUpdate,
    RunStatus,
    TrackingEventCreate,
    utc_now,
)

SCHEMA_VERSION = 2


class StoreError(RuntimeError):
    """Raised when a requested record cannot be created or located."""


class SQLiteStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._write_lock = threading.RLock()

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=30, check_same_thread=False)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 30000")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self) -> None:
        with self._write_lock, self.connection() as db:
            db.execute("PRAGMA journal_mode = WAL")
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS schema_version (
                    version INTEGER NOT NULL,
                    applied_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS campaigns (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    slug TEXT NOT NULL UNIQUE,
                    product_name TEXT NOT NULL,
                    product_url TEXT NOT NULL,
                    audience TEXT NOT NULL,
                    market TEXT NOT NULL,
                    language TEXT NOT NULL,
                    channels_json TEXT NOT NULL,
                    goals_json TEXT NOT NULL,
                    product_facts_json TEXT NOT NULL,
                    prohibited_claims_json TEXT NOT NULL,
                    schedule_cron TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    next_run_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS campaign_runs (
                    id TEXT PRIMARY KEY,
                    campaign_id TEXT NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
                    workflow TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    status TEXT NOT NULL,
                    requested_channels_json TEXT NOT NULL,
                    started_at TEXT,
                    finished_at TEXT,
                    error TEXT,
                    summary_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS artifacts (
                    id TEXT PRIMARY KEY,
                    campaign_id TEXT NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
                    run_id TEXT NOT NULL REFERENCES campaign_runs(id) ON DELETE CASCADE,
                    agent TEXT NOT NULL,
                    artifact_type TEXT NOT NULL,
                    channel TEXT NOT NULL,
                    title TEXT NOT NULL,
                    content TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    policy_json TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    reviewed_by TEXT,
                    review_notes TEXT,
                    reviewed_at TEXT,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_artifacts_campaign ON artifacts(campaign_id, created_at);
                CREATE TABLE IF NOT EXISTS tracking_events (
                    id TEXT PRIMARY KEY,
                    campaign_id TEXT NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
                    artifact_id TEXT,
                    event_type TEXT NOT NULL,
                    source TEXT NOT NULL,
                    medium TEXT NOT NULL,
                    external_event_id TEXT UNIQUE,
                    value REAL NOT NULL,
                    metadata_json TEXT NOT NULL,
                    occurred_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_events_campaign ON tracking_events(campaign_id, occurred_at);
                CREATE TABLE IF NOT EXISTS hourly_sales_reviews (
                    id TEXT PRIMARY KEY,
                    campaign_id TEXT NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
                    hour_bucket TEXT NOT NULL,
                    metrics_json TEXT NOT NULL,
                    readiness_json TEXT NOT NULL,
                    recommendation_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(campaign_id, hour_bucket)
                );
                CREATE INDEX IF NOT EXISTS idx_hourly_sales_reviews_campaign
                    ON hourly_sales_reviews(campaign_id, hour_bucket DESC);
                CREATE TABLE IF NOT EXISTS memories (
                    id TEXT PRIMARY KEY,
                    campaign_id TEXT REFERENCES campaigns(id) ON DELETE CASCADE,
                    tier TEXT NOT NULL,
                    category TEXT NOT NULL,
                    content TEXT NOT NULL,
                    importance REAL NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_memories_campaign ON memories(campaign_id, tier, created_at);
                CREATE TABLE IF NOT EXISTS audit_events (
                    id TEXT PRIMARY KEY,
                    campaign_id TEXT,
                    actor TEXT NOT NULL,
                    action TEXT NOT NULL,
                    object_type TEXT NOT NULL,
                    object_id TEXT NOT NULL,
                    details_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_events(created_at);
                CREATE TABLE IF NOT EXISTS policy_decisions (
                    id TEXT PRIMARY KEY,
                    campaign_id TEXT,
                    run_id TEXT,
                    artifact_id TEXT,
                    allowed INTEGER NOT NULL,
                    findings_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS inference_usage (
                    id TEXT PRIMARY KEY,
                    campaign_id TEXT,
                    run_id TEXT,
                    agent TEXT NOT NULL,
                    model TEXT NOT NULL,
                    prompt_tokens INTEGER NOT NULL,
                    completion_tokens INTEGER NOT NULL,
                    estimated_cost_usd REAL NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_usage_created ON inference_usage(created_at);
                CREATE TABLE IF NOT EXISTS scheduler_leases (
                    name TEXT PRIMARY KEY,
                    holder TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS heartbeat_history (
                    id TEXT PRIMARY KEY,
                    task_name TEXT NOT NULL,
                    status TEXT NOT NULL,
                    details_json TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    finished_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS optimization_proposals (
                    id TEXT PRIMARY KEY,
                    campaign_id TEXT NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
                    run_id TEXT REFERENCES campaign_runs(id) ON DELETE SET NULL,
                    hypothesis TEXT NOT NULL,
                    evidence_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    decided_at TEXT
                );
                """
            )
            row = db.execute("SELECT MAX(version) AS version FROM schema_version").fetchone()
            current_version = int(row["version"] or 0) if row else 0
            if current_version < SCHEMA_VERSION:
                db.execute(
                    "INSERT INTO schema_version(version, applied_at) VALUES (?, ?)",
                    (SCHEMA_VERSION, utc_now()),
                )

    def health(self) -> bool:
        with self.connection() as db:
            return db.execute("SELECT 1 AS ok").fetchone()["ok"] == 1

    @staticmethod
    def _decode(row: sqlite3.Row | None, json_fields: tuple[str, ...]) -> dict[str, Any] | None:
        if row is None:
            return None
        result = dict(row)
        for field in json_fields:
            raw = result.pop(field, "{}")
            result[field.removesuffix("_json")] = json.loads(raw)
        return result

    def create_campaign(self, request: CampaignCreate, product_url: str) -> dict[str, Any]:
        campaign_id = str(uuid.uuid4())
        now = utc_now()
        with self._write_lock, self.connection() as db:
            try:
                db.execute(
                    """
                    INSERT INTO campaigns(
                        id, name, slug, product_name, product_url, audience, market, language,
                        channels_json, goals_json, product_facts_json, prohibited_claims_json,
                        schedule_cron, metadata_json, status, next_run_at, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        campaign_id,
                        request.name,
                        request.slug,
                        request.product_name,
                        product_url,
                        request.audience,
                        request.market,
                        request.language,
                        json.dumps([str(channel) for channel in request.channels]),
                        json.dumps(request.goals, ensure_ascii=False),
                        json.dumps(request.product_facts, ensure_ascii=False),
                        json.dumps(request.prohibited_claims, ensure_ascii=False),
                        request.schedule_cron,
                        json.dumps(request.metadata, ensure_ascii=False),
                        CampaignStatus.DRAFT,
                        None,
                        now,
                        now,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise StoreError(f"campaign slug already exists: {request.slug}") from exc
        self.audit(campaign_id, "owner", "campaign.created", "campaign", campaign_id, {})
        return self.get_campaign(request.slug)

    def seed_campaign(self, request: CampaignCreate, product_url: str) -> dict[str, Any]:
        existing = self.get_campaign(request.slug, required=False)
        return existing or self.create_campaign(request, product_url)

    def get_campaign(self, slug: str, *, required: bool = True) -> dict[str, Any] | None:
        with self.connection() as db:
            row = db.execute("SELECT * FROM campaigns WHERE slug = ?", (slug,)).fetchone()
        result = self._decode(
            row,
            (
                "channels_json",
                "goals_json",
                "product_facts_json",
                "prohibited_claims_json",
                "metadata_json",
            ),
        )
        if required and result is None:
            raise StoreError(f"campaign not found: {slug}")
        return result

    def get_campaign_by_id(self, campaign_id: str) -> dict[str, Any]:
        with self.connection() as db:
            row = db.execute("SELECT * FROM campaigns WHERE id = ?", (campaign_id,)).fetchone()
        result = self._decode(
            row,
            (
                "channels_json",
                "goals_json",
                "product_facts_json",
                "prohibited_claims_json",
                "metadata_json",
            ),
        )
        if result is None:
            raise StoreError(f"campaign not found: {campaign_id}")
        return result

    def list_campaigns(self) -> list[dict[str, Any]]:
        with self.connection() as db:
            rows = db.execute("SELECT * FROM campaigns ORDER BY created_at DESC").fetchall()
        return [
            self._decode(
                row,
                (
                    "channels_json",
                    "goals_json",
                    "product_facts_json",
                    "prohibited_claims_json",
                    "metadata_json",
                ),
            )
            for row in rows
        ]

    def update_campaign(self, slug: str, request: CampaignUpdate) -> dict[str, Any]:
        campaign = self.get_campaign(slug)
        updates = request.model_dump(exclude_none=True)
        if not updates:
            return campaign
        json_columns = {"channels", "goals", "product_facts", "prohibited_claims", "metadata"}
        columns: list[str] = []
        values: list[Any] = []
        for key, value in updates.items():
            if key in json_columns:
                key = f"{key}_json"
                if isinstance(value, list):
                    value = [str(item) for item in value]
                value = json.dumps(value, ensure_ascii=False)
            elif key == "status":
                value = str(value)
            columns.append(f"{key} = ?")
            values.append(value)
        columns.append("updated_at = ?")
        values.extend([utc_now(), campaign["id"]])
        with self._write_lock, self.connection() as db:
            # Column names come only from the validated CampaignUpdate whitelist.
            db.execute(
                f"UPDATE campaigns SET {', '.join(columns)} WHERE id = ?",  # noqa: S608
                values,
            )
        self.audit(campaign["id"], "owner", "campaign.updated", "campaign", campaign["id"], updates)
        return self.get_campaign(slug)

    def clone_campaign(
        self,
        source_slug: str,
        request: CampaignCloneRequest,
        default_product_url: str,
    ) -> dict[str, Any]:
        source = self.get_campaign(source_slug)
        clone = CampaignCreate(
            name=request.name,
            slug=request.slug,
            product_name=request.product_name or source["product_name"],
            product_url=request.product_url,
            audience=request.audience or source["audience"],
            market=source["market"],
            language=source["language"],
            channels=source["channels"],
            goals=source["goals"],
            product_facts=[] if request.reset_product_facts else source["product_facts"],
            prohibited_claims=source["prohibited_claims"],
            schedule_cron=source["schedule_cron"],
            metadata={**source["metadata"], "cloned_from": source_slug},
        )
        product_url = str(request.product_url or default_product_url or source["product_url"])
        created = self.create_campaign(clone, product_url)
        self.audit(
            created["id"],
            "owner",
            "campaign.cloned",
            "campaign",
            created["id"],
            {"source_campaign": source_slug, "facts_reset": request.reset_product_facts},
        )
        return created

    def create_run(
        self,
        campaign_id: str,
        workflow: str,
        channels: list[str],
        idempotency_key: str,
    ) -> tuple[dict[str, Any], bool]:
        run_id = str(uuid.uuid4())
        created = False
        with self._write_lock, self.connection() as db:
            try:
                db.execute(
                    """INSERT INTO campaign_runs(
                    id, campaign_id, workflow, idempotency_key, status,
                    requested_channels_json, summary_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        run_id,
                        campaign_id,
                        workflow,
                        idempotency_key,
                        RunStatus.QUEUED,
                        json.dumps(channels),
                        "{}",
                        utc_now(),
                    ),
                )
                created = True
            except sqlite3.IntegrityError:
                row = db.execute(
                    "SELECT * FROM campaign_runs WHERE idempotency_key = ?", (idempotency_key,)
                ).fetchone()
                if row is None:
                    raise
                run_id = row["id"]
        return self.get_run(run_id), created

    def get_run(self, run_id: str) -> dict[str, Any]:
        with self.connection() as db:
            row = db.execute("SELECT * FROM campaign_runs WHERE id = ?", (run_id,)).fetchone()
        result = self._decode(row, ("requested_channels_json", "summary_json"))
        if result is None:
            raise StoreError(f"run not found: {run_id}")
        return result

    def claim_run(self, run_id: str) -> bool:
        with self._write_lock, self.connection() as db:
            cursor = db.execute(
                """UPDATE campaign_runs SET status = ?, started_at = ?,
                finished_at = NULL, error = NULL
                WHERE id = ? AND status IN (?, ?)""",
                (
                    RunStatus.RUNNING,
                    utc_now(),
                    run_id,
                    RunStatus.QUEUED,
                    RunStatus.FAILED,
                ),
            )
            return cursor.rowcount == 1

    def update_run(
        self,
        run_id: str,
        status: RunStatus,
        *,
        summary: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> dict[str, Any]:
        now = utc_now()
        started_at = now if status == RunStatus.RUNNING else None
        finished_at = now if status in {
            RunStatus.AWAITING_APPROVAL,
            RunStatus.COMPLETED,
            RunStatus.FAILED,
            RunStatus.REJECTED,
        } else None
        with self._write_lock, self.connection() as db:
            db.execute(
                """UPDATE campaign_runs SET status = ?,
                started_at = COALESCE(started_at, ?),
                finished_at = COALESCE(?, finished_at), error = ?, summary_json = ?
                WHERE id = ?""",
                (
                    status,
                    started_at,
                    finished_at,
                    error,
                    json.dumps(summary or {}, ensure_ascii=False),
                    run_id,
                ),
            )
        return self.get_run(run_id)

    def list_runs(self, campaign_id: str, limit: int = 50) -> list[dict[str, Any]]:
        with self.connection() as db:
            rows = db.execute(
                "SELECT * FROM campaign_runs WHERE campaign_id = ? ORDER BY created_at DESC LIMIT ?",
                (campaign_id, limit),
            ).fetchall()
        return [self._decode(row, ("requested_channels_json", "summary_json")) for row in rows]

    def create_artifact(
        self,
        *,
        campaign_id: str,
        run_id: str,
        agent: str,
        artifact_type: str,
        channel: str,
        title: str,
        content: str,
        metadata: dict[str, Any],
        policy: dict[str, Any],
    ) -> dict[str, Any]:
        artifact_id = str(uuid.uuid4())
        with self._write_lock, self.connection() as db:
            version = db.execute(
                """SELECT COALESCE(MAX(version), 0) + 1 AS version FROM artifacts
                WHERE campaign_id = ? AND artifact_type = ? AND channel = ?""",
                (campaign_id, artifact_type, channel),
            ).fetchone()["version"]
            db.execute(
                """INSERT INTO artifacts(
                id, campaign_id, run_id, agent, artifact_type, channel, title, content,
                metadata_json, policy_json, version, status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    artifact_id,
                    campaign_id,
                    run_id,
                    agent,
                    artifact_type,
                    channel,
                    title,
                    content,
                    json.dumps(metadata, ensure_ascii=False),
                    json.dumps(policy, ensure_ascii=False),
                    version,
                    ArtifactStatus.DRAFT,
                    utc_now(),
                ),
            )
        return self.get_artifact(artifact_id)

    def get_artifact(self, artifact_id: str) -> dict[str, Any]:
        with self.connection() as db:
            row = db.execute("SELECT * FROM artifacts WHERE id = ?", (artifact_id,)).fetchone()
        result = self._decode(row, ("metadata_json", "policy_json"))
        if result is None:
            raise StoreError(f"artifact not found: {artifact_id}")
        return result

    def list_artifacts(
        self, campaign_id: str, status: str | None = None, limit: int = 100
    ) -> list[dict[str, Any]]:
        query = "SELECT * FROM artifacts WHERE campaign_id = ?"
        values: list[Any] = [campaign_id]
        if status:
            query += " AND status = ?"
            values.append(status)
        query += " ORDER BY created_at DESC LIMIT ?"
        values.append(limit)
        with self.connection() as db:
            rows = db.execute(query, values).fetchall()
        return [self._decode(row, ("metadata_json", "policy_json")) for row in rows]

    def review_artifact(
        self, artifact_id: str, decision: ArtifactStatus, reviewer: str, notes: str
    ) -> dict[str, Any]:
        artifact = self.get_artifact(artifact_id)
        with self._write_lock, self.connection() as db:
            db.execute(
                """UPDATE artifacts SET status = ?, reviewed_by = ?, review_notes = ?,
                reviewed_at = ? WHERE id = ?""",
                (decision, reviewer, notes, utc_now(), artifact_id),
            )
        self.audit(
            artifact["campaign_id"], reviewer, f"artifact.{decision}", "artifact", artifact_id,
            {"notes": notes},
        )
        return self.get_artifact(artifact_id)

    def record_policy_decision(
        self,
        campaign_id: str,
        run_id: str,
        artifact_id: str,
        allowed: bool,
        findings: list[dict[str, Any]],
    ) -> None:
        with self._write_lock, self.connection() as db:
            db.execute(
                """INSERT INTO policy_decisions(
                id, campaign_id, run_id, artifact_id, allowed, findings_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    str(uuid.uuid4()), campaign_id, run_id, artifact_id, int(allowed),
                    json.dumps(findings, ensure_ascii=False), utc_now(),
                ),
            )

    def record_tracking_event(self, event: TrackingEventCreate) -> tuple[dict[str, Any], bool]:
        campaign = self.get_campaign(event.campaign_slug)
        record_id = str(uuid.uuid4())
        external_id = event.event_id or None
        with self._write_lock, self.connection() as db:
            try:
                db.execute(
                    """INSERT INTO tracking_events(
                    id, campaign_id, artifact_id, event_type, source, medium,
                    external_event_id, value, metadata_json, occurred_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        record_id,
                        campaign["id"],
                        event.content_id or None,
                        event.event_type,
                        event.source,
                        event.medium,
                        external_id,
                        event.value,
                        json.dumps(event.metadata, ensure_ascii=False),
                        utc_now(),
                    ),
                )
                created = True
            except sqlite3.IntegrityError:
                row = db.execute(
                    "SELECT * FROM tracking_events WHERE external_event_id = ?", (external_id,)
                ).fetchone()
                if row is None:
                    raise
                record_id = row["id"]
                created = False
            row = db.execute("SELECT * FROM tracking_events WHERE id = ?", (record_id,)).fetchone()
        return self._decode(row, ("metadata_json",)), created

    def campaign_metrics(self, campaign_id: str) -> dict[str, Any]:
        with self.connection() as db:
            totals = db.execute(
                """SELECT
                SUM(CASE WHEN event_type = 'view' THEN 1 ELSE 0 END) AS views,
                SUM(CASE WHEN event_type = 'click' THEN 1 ELSE 0 END) AS clicks,
                SUM(CASE WHEN event_type = 'signup' THEN 1 ELSE 0 END) AS signups,
                SUM(CASE WHEN event_type = 'conversion' THEN 1 ELSE 0 END) AS conversions,
                SUM(CASE WHEN event_type = 'conversion' THEN value ELSE 0 END) AS value
                FROM tracking_events WHERE campaign_id = ?""",
                (campaign_id,),
            ).fetchone()
            by_source = db.execute(
                """SELECT source, event_type, COUNT(*) AS count, SUM(value) AS value
                FROM tracking_events WHERE campaign_id = ?
                GROUP BY source, event_type ORDER BY count DESC""",
                (campaign_id,),
            ).fetchall()
        values = {key: (totals[key] or 0) for key in totals.keys()}
        clicks = int(values["clicks"])
        views = int(values["views"])
        conversions = int(values["conversions"])
        values["ctr"] = round(clicks / views, 4) if views else 0.0
        values["conversion_rate"] = round(conversions / clicks, 4) if clicks else 0.0
        values["by_source"] = [dict(row) for row in by_source]
        return values

    def create_hourly_sales_review(
        self,
        campaign_id: str,
        hour_bucket: str,
        metrics: dict[str, Any],
        readiness: dict[str, Any],
        recommendation: dict[str, Any],
    ) -> tuple[dict[str, Any], bool]:
        """Create one review per campaign per UTC hour, or return its prior record."""
        review_id = str(uuid.uuid4())
        with self._write_lock, self.connection() as db:
            try:
                db.execute(
                    """INSERT INTO hourly_sales_reviews(
                    id, campaign_id, hour_bucket, metrics_json, readiness_json,
                    recommendation_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        review_id,
                        campaign_id,
                        hour_bucket,
                        json.dumps(metrics, ensure_ascii=False),
                        json.dumps(readiness, ensure_ascii=False),
                        json.dumps(recommendation, ensure_ascii=False),
                        utc_now(),
                    ),
                )
                created = True
            except sqlite3.IntegrityError:
                row = db.execute(
                    """SELECT * FROM hourly_sales_reviews
                    WHERE campaign_id = ? AND hour_bucket = ?""",
                    (campaign_id, hour_bucket),
                ).fetchone()
                if row is None:
                    raise
                return self._decode_hourly_sales_review(row), False
            row = db.execute(
                "SELECT * FROM hourly_sales_reviews WHERE id = ?", (review_id,)
            ).fetchone()
        return self._decode_hourly_sales_review(row), created

    def get_hourly_sales_review(
        self, campaign_id: str, hour_bucket: str
    ) -> dict[str, Any] | None:
        with self.connection() as db:
            row = db.execute(
                """SELECT * FROM hourly_sales_reviews
                WHERE campaign_id = ? AND hour_bucket = ?""",
                (campaign_id, hour_bucket),
            ).fetchone()
        return self._decode_hourly_sales_review(row) if row else None

    def latest_hourly_sales_review(self, campaign_id: str) -> dict[str, Any] | None:
        with self.connection() as db:
            row = db.execute(
                """SELECT * FROM hourly_sales_reviews WHERE campaign_id = ?
                ORDER BY hour_bucket DESC LIMIT 1""",
                (campaign_id,),
            ).fetchone()
        return self._decode_hourly_sales_review(row) if row else None

    def list_hourly_sales_reviews(self, campaign_id: str, limit: int = 72) -> list[dict[str, Any]]:
        with self.connection() as db:
            rows = db.execute(
                """SELECT * FROM hourly_sales_reviews WHERE campaign_id = ?
                ORDER BY hour_bucket DESC LIMIT ?""",
                (campaign_id, limit),
            ).fetchall()
        return [self._decode_hourly_sales_review(row) for row in rows]

    @staticmethod
    def _decode_hourly_sales_review(row: sqlite3.Row) -> dict[str, Any]:
        return SQLiteStore._decode(
            row, ("metrics_json", "readiness_json", "recommendation_json")
        )

    def campaign_attribution(self, campaign_id: str) -> list[dict[str, Any]]:
        """Return aggregate channel attribution without event metadata or identifiers."""
        with self.connection() as db:
            rows = db.execute(
                """SELECT source, medium, COALESCE(artifact_id, '') AS content_id,
                event_type, COUNT(*) AS count
                FROM tracking_events WHERE campaign_id = ?
                GROUP BY source, medium, artifact_id, event_type
                ORDER BY count DESC""",
                (campaign_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def campaign_daily_metrics(
        self, campaign_id: str, days: int = 7, timezone_name: str = "Europe/Amsterdam"
    ) -> list[dict[str, Any]]:
        """Return complete local-day metric buckets for public charting without raw events."""
        timezone = ZoneInfo(timezone_name)
        end_date = datetime.now(timezone).date()
        start_date = end_date - timedelta(days=max(1, days) - 1)
        buckets: dict[date, dict[str, int]] = {
            start_date + timedelta(days=offset): {
                "views": 0,
                "clicks": 0,
                "signups": 0,
                "conversions": 0,
            }
            for offset in range((end_date - start_date).days + 1)
        }
        start_at = datetime.combine(start_date, time.min, tzinfo=timezone).astimezone(UTC).isoformat()
        with self.connection() as db:
            rows = db.execute(
                """SELECT occurred_at, event_type, COUNT(*) AS count
                FROM tracking_events
                WHERE campaign_id = ? AND occurred_at >= ?
                GROUP BY occurred_at, event_type""",
                (campaign_id, start_at),
            ).fetchall()
        metric_keys = {
            "view": "views",
            "click": "clicks",
            "signup": "signups",
            "conversion": "conversions",
        }
        for row in rows:
            occurred_at = datetime.fromisoformat(str(row["occurred_at"])).astimezone(timezone)
            metric_key = metric_keys.get(str(row["event_type"]).rsplit(".", maxsplit=1)[-1].lower())
            if metric_key and occurred_at.date() in buckets:
                buckets[occurred_at.date()][metric_key] += int(row["count"])
        return [
            {"date": day.isoformat(), "metrics": metrics}
            for day, metrics in sorted(buckets.items())
        ]

    def verified_conversion_summary(self, campaign_ids: list[str]) -> dict[str, Any]:
        """Return public-safe PayPro callback freshness for active campaign evidence windows."""
        if not campaign_ids:
            return {"count": 0, "latest_at": None}
        with self.connection() as db:
            row = db.execute(
                """SELECT COUNT(*) AS count, MAX(occurred_at) AS latest_at
                FROM tracking_events
                WHERE campaign_id IN (SELECT value FROM json_each(?))
                  AND event_type = 'conversion'
                  AND source = 'paypro'""",
                (json.dumps(campaign_ids),),
            ).fetchone()
        return {"count": int(row["count"] or 0), "latest_at": row["latest_at"]}

    def remember(
        self,
        campaign_id: str | None,
        tier: str,
        category: str,
        content: str,
        importance: float = 0.5,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        memory_id = str(uuid.uuid4())
        with self._write_lock, self.connection() as db:
            db.execute(
                """INSERT INTO memories(
                id, campaign_id, tier, category, content, importance, metadata_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    memory_id, campaign_id, tier, category, content,
                    max(0.0, min(1.0, importance)), json.dumps(metadata or {}, ensure_ascii=False),
                    utc_now(),
                ),
            )
        return memory_id

    def recall(self, campaign_id: str, limit: int = 20) -> list[dict[str, Any]]:
        with self.connection() as db:
            rows = db.execute(
                """SELECT * FROM memories WHERE campaign_id = ? OR campaign_id IS NULL
                ORDER BY importance DESC, created_at DESC LIMIT ?""",
                (campaign_id, limit),
            ).fetchall()
        return [self._decode(row, ("metadata_json",)) for row in rows]

    def record_inference_usage(
        self,
        campaign_id: str,
        run_id: str,
        agent: str,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        estimated_cost_usd: float,
    ) -> None:
        with self._write_lock, self.connection() as db:
            db.execute(
                """INSERT INTO inference_usage(
                id, campaign_id, run_id, agent, model, prompt_tokens, completion_tokens,
                estimated_cost_usd, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    str(uuid.uuid4()), campaign_id, run_id, agent, model,
                    prompt_tokens, completion_tokens, estimated_cost_usd, utc_now(),
                ),
            )

    def usage_counts(self) -> dict[str, int]:
        now = datetime.now(UTC)
        hour = (now - timedelta(hours=1)).isoformat()
        day = (now - timedelta(days=1)).isoformat()
        with self.connection() as db:
            row = db.execute(
                """SELECT
                SUM(CASE WHEN created_at >= ? THEN 1 ELSE 0 END) AS hourly,
                SUM(CASE WHEN created_at >= ? THEN 1 ELSE 0 END) AS daily
                FROM inference_usage""",
                (hour, day),
            ).fetchone()
        return {"hourly": int(row["hourly"] or 0), "daily": int(row["daily"] or 0)}

    def audit(
        self,
        campaign_id: str | None,
        actor: str,
        action: str,
        object_type: str,
        object_id: str,
        details: dict[str, Any],
    ) -> None:
        with self._write_lock, self.connection() as db:
            db.execute(
                """INSERT INTO audit_events(
                id, campaign_id, actor, action, object_type, object_id, details_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    str(uuid.uuid4()), campaign_id, actor, action, object_type, object_id,
                    json.dumps(details, ensure_ascii=False, default=str), utc_now(),
                ),
            )

    def list_audit(self, campaign_id: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        query = "SELECT * FROM audit_events"
        values: list[Any] = []
        if campaign_id:
            query += " WHERE campaign_id = ?"
            values.append(campaign_id)
        query += " ORDER BY created_at DESC LIMIT ?"
        values.append(limit)
        with self.connection() as db:
            rows = db.execute(query, values).fetchall()
        return [self._decode(row, ("details_json",)) for row in rows]

    def acquire_lease(self, name: str, holder: str, ttl_seconds: int = 60) -> bool:
        now = datetime.now(UTC)
        expires = (now + timedelta(seconds=ttl_seconds)).isoformat()
        with self._write_lock, self.connection() as db:
            row = db.execute(
                "SELECT holder, expires_at FROM scheduler_leases WHERE name = ?", (name,)
            ).fetchone()
            if row and datetime.fromisoformat(row["expires_at"]) > now and row["holder"] != holder:
                return False
            db.execute(
                """INSERT INTO scheduler_leases(name, holder, expires_at, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET holder=excluded.holder,
                expires_at=excluded.expires_at, updated_at=excluded.updated_at""",
                (name, holder, expires, now.isoformat()),
            )
        return True

    def release_lease(self, name: str, holder: str) -> None:
        with self._write_lock, self.connection() as db:
            db.execute("DELETE FROM scheduler_leases WHERE name = ? AND holder = ?", (name, holder))

    def record_heartbeat(
        self, task_name: str, status: str, details: dict[str, Any], started_at: str
    ) -> None:
        with self._write_lock, self.connection() as db:
            db.execute(
                """INSERT INTO heartbeat_history(
                id, task_name, status, details_json, started_at, finished_at
                ) VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    str(uuid.uuid4()), task_name, status,
                    json.dumps(details, ensure_ascii=False, default=str), started_at, utc_now(),
                ),
            )

    def latest_heartbeats(self, limit: int = 20) -> list[dict[str, Any]]:
        with self.connection() as db:
            rows = db.execute(
                "SELECT * FROM heartbeat_history ORDER BY started_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [self._decode(row, ("details_json",)) for row in rows]

    def create_optimization_proposal(
        self,
        campaign_id: str,
        run_id: str | None,
        hypothesis: str,
        evidence: dict[str, Any],
    ) -> dict[str, Any]:
        proposal_id = str(uuid.uuid4())
        with self._write_lock, self.connection() as db:
            db.execute(
                """INSERT INTO optimization_proposals(
                id, campaign_id, run_id, hypothesis, evidence_json, status, created_at
                ) VALUES (?, ?, ?, ?, ?, 'proposed', ?)""",
                (
                    proposal_id, campaign_id, run_id, hypothesis,
                    json.dumps(evidence, ensure_ascii=False), utc_now(),
                ),
            )
            row = db.execute(
                "SELECT * FROM optimization_proposals WHERE id = ?", (proposal_id,)
            ).fetchone()
        return self._decode(row, ("evidence_json",))

    def due_campaigns(self, at: str | None = None) -> list[dict[str, Any]]:
        at = at or utc_now()
        with self.connection() as db:
            rows = db.execute(
                """SELECT * FROM campaigns
                WHERE status = ? AND (next_run_at IS NULL OR next_run_at <= ?)
                ORDER BY COALESCE(next_run_at, created_at) ASC""",
                (CampaignStatus.ACTIVE, at),
            ).fetchall()
        return [
            self._decode(
                row,
                (
                    "channels_json",
                    "goals_json",
                    "product_facts_json",
                    "prohibited_claims_json",
                    "metadata_json",
                ),
            )
            for row in rows
        ]

    def set_next_run(self, campaign_id: str, next_run_at: str) -> None:
        with self._write_lock, self.connection() as db:
            db.execute(
                "UPDATE campaigns SET next_run_at = ?, updated_at = ? WHERE id = ?",
                (next_run_at, utc_now(), campaign_id),
            )

    def queued_runs(self, limit: int = 20) -> list[dict[str, Any]]:
        with self.connection() as db:
            rows = db.execute(
                """SELECT * FROM campaign_runs WHERE status = ?
                ORDER BY created_at ASC LIMIT ?""",
                (RunStatus.QUEUED, limit),
            ).fetchall()
        return [self._decode(row, ("requested_channels_json", "summary_json")) for row in rows]

    def recover_stale_runs(self, stale_after_minutes: int = 60) -> int:
        cutoff = (datetime.now(UTC) - timedelta(minutes=stale_after_minutes)).isoformat()
        with self._write_lock, self.connection() as db:
            cursor = db.execute(
                """UPDATE campaign_runs SET status = ?, error = ?, finished_at = ?
                WHERE status = ? AND started_at IS NOT NULL AND started_at < ?""",
                (
                    RunStatus.FAILED,
                    "Recovered as failed after stale running lease",
                    utc_now(),
                    RunStatus.RUNNING,
                    cutoff,
                ),
            )
            return cursor.rowcount

    def list_optimization_proposals(
        self, campaign_id: str, limit: int = 100
    ) -> list[dict[str, Any]]:
        with self.connection() as db:
            rows = db.execute(
                """SELECT * FROM optimization_proposals WHERE campaign_id = ?
                ORDER BY created_at DESC LIMIT ?""",
                (campaign_id, limit),
            ).fetchall()
        return [self._decode(row, ("evidence_json",)) for row in rows]

    def decide_optimization(
        self,
        proposal_id: str,
        decision: str,
        reviewer: str,
        notes: str,
    ) -> dict[str, Any]:
        with self._write_lock, self.connection() as db:
            row = db.execute(
                "SELECT * FROM optimization_proposals WHERE id = ?", (proposal_id,)
            ).fetchone()
            if row is None:
                raise StoreError(f"optimization proposal not found: {proposal_id}")
            db.execute(
                """UPDATE optimization_proposals SET status = ?, decided_at = ?
                WHERE id = ?""",
                (decision, utc_now(), proposal_id),
            )
            updated = db.execute(
                "SELECT * FROM optimization_proposals WHERE id = ?", (proposal_id,)
            ).fetchone()
        self.audit(
            row["campaign_id"],
            reviewer,
            f"optimization.{decision}",
            "optimization_proposal",
            proposal_id,
            {"notes": notes},
        )
        return self._decode(updated, ("evidence_json",))
