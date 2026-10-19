"""Read-only access to previously written historical-simulation report runs.

The project's historical simulation runs as a command-line tool and writes each
run to its own timestamped directory. Nothing else reads those files today, so
the dashboard could not show a run's provenance or results.

This module adds a strictly read-only view over that directory:

* :func:`list_runs` enumerates the run directories newest first and extracts the
  honest provenance metadata from each run's machine-readable summary;
* :func:`load_run` returns one run's parsed summary plus its file listing;
* :func:`read_artifact` returns the raw bytes of one artifact for download.

Safety
------
This module never writes, deletes or regenerates a report, so a previous run is
never overwritten or mixed with another. Every path is confined to a single run
directory under the configured root: a ``run_id`` or filename containing a path
separator or a ``..`` segment is rejected, so a request can never escape the
reports directory. It imports no MetaTrader or execution code.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from app.config import PROJECT_ROOT

__all__ = [
    "DEFAULT_REPORTS_DIR",
    "ReportError",
    "ReportRunNotFound",
    "list_runs",
    "load_run",
    "read_artifact",
    "resolve_reports_dir",
]

# The directory the historical-simulation command-line tool writes its runs into.
# Kept in step with that tool's default output directory.
DEFAULT_REPORTS_DIR = PROJECT_ROOT / "reports" / "backtests"

# A run is identified by a machine-readable summary. Two report families exist:
# the per-timeframe run and the exit-policy comparison.
SUMMARY_FILENAMES = ("summary.json", "comparison_summary.json")

# A single, safe path segment: letters, digits, dot, underscore and hyphen only.
_SEGMENT = re.compile(r"^[A-Za-z0-9._-]+$")


class ReportError(Exception):
    """A report could not be read (malformed run id, missing file, ...)."""


class ReportRunNotFound(ReportError):
    """The requested run or artifact does not exist."""


def resolve_reports_dir(configured: Optional[str]) -> Path:
    """Return the reports root, honouring an explicit configured override.

    An empty override falls back to :data:`DEFAULT_REPORTS_DIR` - the directory
    the historical-simulation and research CLI tools write into - so the
    read-only dashboard finds their runs without extra configuration.
    """
    if configured and configured.strip():
        return Path(configured.strip())
    return DEFAULT_REPORTS_DIR


def _single_segment(value: str, *, kind: str) -> str:
    text = (value or "").strip()
    if not text or text in {".", ".."} or not _SEGMENT.match(text):
        raise ReportError(f"Invalid {kind}.")
    return text


def _run_dir(root: Path, run_id: str) -> Path:
    safe_id = _single_segment(run_id, kind="run id")
    root_resolved = root.resolve()
    candidate = (root_resolved / safe_id).resolve()
    # Confinement check: the resolved run directory must live directly under the
    # configured reports root.
    if candidate.parent != root_resolved:
        raise ReportError("Run id escapes the reports directory.")
    if not candidate.is_dir():
        raise ReportRunNotFound(f"Report run {safe_id!r} was not found.")
    return candidate


def _load_json(path: Path) -> Optional[dict[str, Any]]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _find_summary(run_dir: Path) -> tuple[Optional[str], Optional[dict[str, Any]]]:
    for name in SUMMARY_FILENAMES:
        candidate = run_dir / name
        if candidate.is_file():
            return name, _load_json(candidate)
    return None, None


def _iso(value: Any) -> Optional[str]:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, str) and value:
        return value
    return None


def _mtime_iso(run_dir: Path) -> Optional[str]:
    try:
        stamp = run_dir.stat().st_mtime
    except OSError:
        return None
    return datetime.fromtimestamp(stamp, tz=timezone.utc).isoformat()


def _looks_like_run(run_dir: Path) -> bool:
    """A directory with no summary is still shown if it holds report artifacts."""
    try:
        return any(entry.is_file() for entry in run_dir.iterdir())
    except OSError:
        return False


def _run_metadata(run_dir: Path, summary: Optional[dict[str, Any]]) -> dict[str, Any]:
    summary = summary or {}
    files = sorted(entry.name for entry in run_dir.iterdir() if entry.is_file())
    count = summary.get("timeframe_count")
    if not isinstance(count, int):
        timeframes = summary.get("timeframes") or summary.get("timeframes_requested")
        count = len(timeframes) if isinstance(timeframes, list) else None
    return {
        "run_id": run_dir.name,
        "report_type": summary.get("report_type") or "unknown",
        "generated_at_utc": _iso(summary.get("generated_at_utc")) or _mtime_iso(run_dir),
        "generated_at_ist": _iso(summary.get("generated_at_ist")),
        "symbol": summary.get("symbol_resolved") or summary.get("symbol"),
        "requested_start_utc": _iso(summary.get("requested_start_utc")),
        "requested_end_utc": _iso(summary.get("requested_end_utc")),
        "timeframes": summary.get("timeframes_requested") or summary.get("timeframes") or [],
        "timeframe_count": count,
        "strategy_fingerprint": summary.get("strategy_fingerprint"),
        "output_dir": str(run_dir),
        "files": files,
        "summary_available": summary.get("report_type") is not None,
    }


def list_runs(root: Path) -> list[dict[str, Any]]:
    """Return every run newest first, with its honest provenance metadata."""
    if not root.is_dir():
        return []
    runs: list[dict[str, Any]] = []
    for entry in root.iterdir():
        if not entry.is_dir():
            continue
        _, summary = _find_summary(entry)
        if summary is None and not _looks_like_run(entry):
            continue
        runs.append(_run_metadata(entry, summary))
    # Newest first by the recorded generation time, falling back to name order.
    runs.sort(key=lambda item: (item.get("generated_at_utc") or "", item["run_id"]), reverse=True)
    return runs


def load_run(root: Path, run_id: str) -> dict[str, Any]:
    """Return one run's metadata plus its fully parsed summary."""
    run_dir = _run_dir(root, run_id)
    summary_file, summary = _find_summary(run_dir)
    metadata = _run_metadata(run_dir, summary)
    metadata["summary_file"] = summary_file
    metadata["summary"] = summary
    return metadata


def read_artifact(root: Path, run_id: str, filename: str) -> tuple[bytes, str]:
    """Return ``(bytes, media_type)`` for one artifact inside a run directory."""
    run_dir = _run_dir(root, run_id)
    safe_name = _single_segment(filename, kind="filename")
    candidate = run_dir / safe_name
    if not candidate.is_file():
        raise ReportRunNotFound(f"Artifact {safe_name!r} was not found in run {run_id!r}.")
    try:
        payload = candidate.read_bytes()
    except OSError as exc:  # pragma: no cover - defensive
        raise ReportError(f"Could not read {safe_name!r}.") from exc
    return payload, _media_type(safe_name)


_TEXT_TYPES = {"json": "application/json", "csv": "text/csv", "md": "text/markdown"}


def _media_type(name: str) -> str:
    suffix = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    return _TEXT_TYPES.get(suffix, "application/octet-stream")
