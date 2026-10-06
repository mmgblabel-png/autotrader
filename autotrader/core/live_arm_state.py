from __future__ import annotations

import json
import os
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class LiveArmRecord:
    armed: bool
    release_id: str
    updated_at: float
    source: str = "operator"

    def as_dict(self) -> dict[str, Any]:
        return {
            "version": 1,
            "armed": bool(self.armed),
            "release_id": str(self.release_id or ""),
            "updated_at": float(self.updated_at),
            "source": str(self.source or "operator"),
        }


class LiveArmIntentStore:
    """Persist operator live intent on durable storage.

    Safety properties:
    - corrupt/missing state fails closed (unarmed)
    - activation persistence is atomic
    - auto-resume is allowed only for the same release id
    - a new code release therefore always requires a fresh operator arm
    """

    def __init__(
        self,
        path: str | Path | None = None,
        *,
        release_id: str | None = None,
        allow_cross_release_resume: bool = False,
    ) -> None:
        self.path = Path(
            path
            or os.getenv(
                "AUTOTRADER_LIVE_ARM_STATE_PATH",
                "/data/live_arm_state.json",
            )
        )
        self.release_id = str(
            release_id
            if release_id is not None
            else os.getenv(
                "RAILWAY_DEPLOYMENT_ID",
                os.getenv("RAILWAY_GIT_COMMIT_SHA", os.getenv("AUTOTRADER_RELEASE_ID", "")),
            )
        ).strip()
        self.allow_cross_release_resume = bool(allow_cross_release_resume)

    def load(self) -> LiveArmRecord:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return LiveArmRecord(False, "", 0.0, "missing")
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            return LiveArmRecord(False, "", 0.0, "invalid")

        if not isinstance(raw, dict) or int(raw.get("version", 0) or 0) != 1:
            return LiveArmRecord(False, "", 0.0, "invalid")

        try:
            updated_at = float(raw.get("updated_at", 0.0) or 0.0)
        except (TypeError, ValueError):
            updated_at = 0.0

        return LiveArmRecord(
            armed=bool(raw.get("armed", False)),
            release_id=str(raw.get("release_id", "") or "").strip(),
            updated_at=max(0.0, updated_at),
            source=str(raw.get("source", "operator") or "operator"),
        )

    def should_resume(self) -> bool:
        record = self.load()
        if not record.armed:
            return False
        if self.allow_cross_release_resume:
            return True
        if not self.release_id:
            return False
        return bool(record.release_id and record.release_id == self.release_id)

    def write(self, armed: bool, *, source: str = "operator") -> LiveArmRecord:
        record = LiveArmRecord(
            armed=bool(armed),
            release_id=self.release_id,
            updated_at=time.time(),
            source=source,
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)

        fd, tmp_name = tempfile.mkstemp(
            prefix=f".{self.path.name}.",
            suffix=".tmp",
            dir=str(self.path.parent),
            text=True,
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(record.as_dict(), handle, sort_keys=True, separators=(",", ":"))
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_name, self.path)
            try:
                dir_fd = os.open(str(self.path.parent), os.O_DIRECTORY)
                try:
                    os.fsync(dir_fd)
                finally:
                    os.close(dir_fd)
            except (AttributeError, OSError):
                pass
        except Exception:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise

        return record

    def status(self) -> dict[str, Any]:
        record = self.load()
        release_match = bool(
            self.release_id
            and record.release_id
            and self.release_id == record.release_id
        )
        return {
            "path": str(self.path),
            "persisted_armed": bool(record.armed),
            "release_match": release_match,
            "auto_resume_eligible": bool(
                record.armed and (release_match or self.allow_cross_release_resume)
            ),
            "cross_release_resume_enabled": self.allow_cross_release_resume,
            "updated_at": float(record.updated_at),
            "source": record.source,
        }
