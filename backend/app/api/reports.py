"""Read-only historical-simulation report endpoints.

The historical simulation itself is a **command-line** tool; the backend only
ever reads the reports it produced. Every endpoint here is a GET: there is no way
to start, re-run or delete a run from the API, so a previous run can never be
overwritten or silently mixed with another.

See :mod:`app.reports.service` for the on-disk layout and the path-confinement
rules that keep reads inside the configured reports directory.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response

from app.config import Settings
from app.errors import ApiError
from app.reports.service import (
    ReportError,
    ReportRunNotFound,
    list_runs,
    load_run,
    read_artifact,
    resolve_reports_dir,
)
from app.schemas.reports import ReportDetailOut, ReportRunOut, ReportsOut
from .deps import get_settings

router = APIRouter(prefix="/api/reports", tags=["reports"])


@router.get(
    "",
    response_model=ReportsOut,
    summary="List previously written report runs",
)
def reports(settings: Settings = Depends(get_settings)) -> ReportsOut:
    """Return every report run on disk, newest first.

    ``available`` is ``False`` when the reports directory does not exist yet,
    which is reported honestly rather than as an empty success.
    """
    root = resolve_reports_dir(settings.reports_dir)
    runs = list_runs(root)
    return ReportsOut(
        reports_root=str(root),
        available=root.is_dir(),
        count=len(runs),
        runs=[ReportRunOut(**run) for run in runs],
    )


@router.get(
    "/{run_id}",
    response_model=ReportDetailOut,
    summary="One report run with its parsed summary",
)
def report_detail(
    run_id: str,
    settings: Settings = Depends(get_settings),
) -> ReportDetailOut:
    """Return one run's provenance metadata plus its parsed summary."""
    root = resolve_reports_dir(settings.reports_dir)
    try:
        detail = load_run(root, run_id)
    except ReportRunNotFound as exc:
        raise ApiError("report_not_found", str(exc), status_code=404) from exc
    except ReportError as exc:
        raise ApiError("report_invalid", str(exc), status_code=400) from exc
    return ReportDetailOut(**detail)


@router.get(
    "/{run_id}/files/{filename}",
    summary="Download one report artifact",
)
def report_file(
    run_id: str,
    filename: str,
    settings: Settings = Depends(get_settings),
) -> Response:
    """Return one report artifact (JSON/CSV/Markdown) as-is.

    The filename is confined to the run directory, so a request can never read
    outside the reports root.
    """
    root = resolve_reports_dir(settings.reports_dir)
    try:
        payload, media_type = read_artifact(root, run_id, filename)
    except ReportRunNotFound as exc:
        raise ApiError("report_not_found", str(exc), status_code=404) from exc
    except ReportError as exc:
        raise ApiError("report_invalid", str(exc), status_code=400) from exc
    return Response(content=payload, media_type=media_type)


__all__ = ["router"]
