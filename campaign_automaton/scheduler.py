"""Durable, lease-protected heartbeat scheduler."""

from __future__ import annotations

import asyncio
import logging
import socket
import uuid
from datetime import UTC, datetime
from typing import Any

from croniter import croniter

from campaign_automaton.config import Settings
from campaign_automaton.models import RunRequest, utc_now
from campaign_automaton.orchestrator import CampaignOrchestrator
from campaign_automaton.store import SQLiteStore

log = logging.getLogger(__name__)


class HeartbeatScheduler:
    def __init__(
        self,
        settings: Settings,
        store: SQLiteStore,
        orchestrator: CampaignOrchestrator,
    ) -> None:
        self.settings = settings
        self.store = store
        self.orchestrator = orchestrator
        self.holder = f"{socket.gethostname()}:{uuid.uuid4()}"
        self._task: asyncio.Task | None = None
        self.running = False
        self.tick_count = 0
        self.last_tick_at: str | None = None
        self.last_error: str | None = None

    async def start(self) -> None:
        if self.running or not self.settings.heartbeat_enabled:
            return
        self.running = True
        self._task = asyncio.create_task(self._loop(), name="campaign-heartbeat")

    async def stop(self) -> None:
        self.running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _loop(self) -> None:
        while self.running:
            await self.tick()
            await asyncio.sleep(self.settings.heartbeat_interval_seconds)

    async def tick(self) -> dict[str, Any]:
        started = utc_now()
        if not self.store.acquire_lease("global-heartbeat", self.holder, ttl_seconds=90):
            return {"status": "skipped", "reason": "lease_held"}
        details: dict[str, Any] = {"recovered_runs": 0, "executed_runs": []}
        try:
            details["recovered_runs"] = self.store.recover_stale_runs()
            for run in self.store.queued_runs(limit=5):
                result = await asyncio.to_thread(self.orchestrator.execute_run, run["id"])
                details["executed_runs"].append(result["id"])
            if self.settings.auto_run_due_campaigns:
                for campaign in self.store.due_campaigns():
                    request = RunRequest(
                        workflow="full_campaign",
                        channels=campaign["channels"],
                        force=False,
                    )
                    run, created = self.orchestrator.queue_run(campaign["slug"], request)
                    if created:
                        result = await asyncio.to_thread(
                            self.orchestrator.execute_run, run["id"]
                        )
                        details["executed_runs"].append(result["id"])
                    next_run = croniter(
                        campaign["schedule_cron"], datetime.now(UTC)
                    ).get_next(datetime)
                    self.store.set_next_run(campaign["id"], next_run.isoformat())
            self.tick_count += 1
            self.last_tick_at = utc_now()
            self.last_error = None
            self.store.record_heartbeat("global-heartbeat", "ok", details, started)
            return {"status": "ok", **details}
        except Exception as exc:
            self.last_error = str(exc)
            log.exception("Heartbeat tick failed")
            self.store.record_heartbeat(
                "global-heartbeat", "error", {"error": str(exc)}, started
            )
            return {"status": "error", "error": str(exc)}
        finally:
            self.store.release_lease("global-heartbeat", self.holder)

    def status(self) -> dict[str, Any]:
        return {
            "enabled": self.settings.heartbeat_enabled,
            "running": self.running,
            "interval_seconds": self.settings.heartbeat_interval_seconds,
            "tick_count": self.tick_count,
            "last_tick_at": self.last_tick_at,
            "last_error": self.last_error,
            "holder": self.holder,
            "history": self.store.latest_heartbeats(limit=5),
        }
