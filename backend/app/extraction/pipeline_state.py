"""
app/extraction/pipeline_state.py
==================================
Async-safe pipeline run registry for the Document Reconstruction Engine.
Tracks 8 stages with per-stage timing, fallback flags, and status.
"""
from __future__ import annotations

import uuid
import time
from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional

STATUS_PENDING = "pending"
STATUS_RUNNING = "running"
STATUS_DONE    = "done"
STATUS_FAILED  = "failed"
STATUS_SKIPPED = "skipped"

PIPELINE_STAGES = [
    "file_ingest",
]

_STAGE_LABELS: Dict[str, str] = {
    "file_ingest": "Extracting Document",
}


@dataclass
class StageRecord:
    stage_id:        str
    label:           str
    status:          str = STATUS_PENDING
    message:         str = ""
    elapsed_ms:      int = 0
    used_fallback:   bool = False
    fallback_reason: str = ""
    extra:           Dict[str, Any] = field(default_factory=dict)
    _start_time:     float = field(default=0.0, repr=False)


class PipelineRun:
    def __init__(self, filename: str) -> None:
        self.run_id         = str(uuid.uuid4())[:16]
        self.filename       = filename
        self.created_at     = time.monotonic()
        self.overall_status = STATUS_RUNNING
        self.error          = ""
        self.result: Optional[Dict] = None
        self.has_partial_result: bool = False
        self.current_message: str = ""
        self.perf_log: List[str]    = []
        self._stages: Dict[str, StageRecord] = {
            sid: StageRecord(stage_id=sid, label=_STAGE_LABELS.get(sid, sid))
            for sid in PIPELINE_STAGES
        }

    # ── Stage control ──────────────────────────────────────────────────────────

    def start_stage(self, stage_id: str, message: str = "") -> None:
        s = self._stages.get(stage_id)
        if not s:
            return
        s.status      = STATUS_RUNNING
        s.message     = message
        self.current_message = message
        s._start_time = time.monotonic()

    def finish_stage(
        self,
        stage_id: str,
        message: str = "",
        used_fallback: bool = False,
        fallback_reason: str = "",
        extra: Optional[Dict] = None,
    ) -> None:
        s = self._stages.get(stage_id)
        if not s:
            return
        s.status          = STATUS_DONE
        s.message         = message
        s.elapsed_ms      = int((time.monotonic() - s._start_time) * 1000)
        s.used_fallback   = used_fallback
        s.fallback_reason = fallback_reason
        s.extra           = extra or {}
        self.perf_log.append(f"[{stage_id}] {s.elapsed_ms}ms — {message}")

    def fail_stage(self, stage_id: str, error: str, timed_out: bool = False) -> None:
        s = self._stages.get(stage_id)
        if not s:
            return
        s.status     = STATUS_FAILED
        s.message    = f"{'TIMEOUT' if timed_out else 'ERROR'}: {error}"
        s.elapsed_ms = int((time.monotonic() - s._start_time) * 1000)

    def abort(self, error: str) -> None:
        self.overall_status = STATUS_FAILED
        self.error          = error

    def complete(self, result: Dict) -> None:
        self.overall_status = STATUS_DONE
        self.result         = result

    # ── Serializers ────────────────────────────────────────────────────────────

    @property
    def progress(self) -> int:
        done = sum(
            1 for s in self._stages.values()
            if s.status in (STATUS_DONE, STATUS_FAILED, STATUS_SKIPPED)
        )
        return int(done / max(len(PIPELINE_STAGES), 1) * 100)

    @property
    def current_stage(self) -> str:
        for sid in PIPELINE_STAGES:
            if self._stages[sid].status == STATUS_RUNNING:
                return sid
        return ""

    def to_status_dict(self) -> Dict:
        return {
            "run_id":         self.run_id,
            "overall_status": self.overall_status,
            "progress":       self.progress,
            "current_stage":  self.current_stage,
            "stages": [
                {
                    "stage_id":      s.stage_id,
                    "label":         s.label,
                    "status":        s.status,
                    "message":       s.message,
                    "elapsed_ms":    s.elapsed_ms,
                    "used_fallback": s.used_fallback,
                }
                for s in self._stages.values()
            ],
            "error": self.error,
            "has_partial_result": self.has_partial_result,
            "current_message": self.current_message,
        }

    def to_full_dict(self) -> Dict:
        d = self.to_status_dict()
        d["result"]   = self.result or {}
        d["perf_log"] = self.perf_log
        d["stages"]   = [
            {
                "stage_id":       s.stage_id,
                "label":          s.label,
                "status":         s.status,
                "message":        s.message,
                "elapsed_ms":     s.elapsed_ms,
                "used_fallback":  s.used_fallback,
                "fallback_reason": s.fallback_reason,
                "extra":          s.extra,
            }
            for s in self._stages.values()
        ]
        return d


# ── Run Registry ───────────────────────────────────────────────────────────────

_RUNS: Dict[str, PipelineRun] = {}
_MAX_RUNS = 100


def create_run(filename: str) -> PipelineRun:
    run = PipelineRun(filename=filename)
    _RUNS[run.run_id] = run
    if len(_RUNS) > _MAX_RUNS:
        oldest = next(iter(_RUNS))
        del _RUNS[oldest]
    return run


def get_run(run_id: str) -> Optional[PipelineRun]:
    return _RUNS.get(run_id)
