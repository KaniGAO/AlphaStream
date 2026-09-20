"""AlphaStream Workbench -- a risk-model observatory, not a product page.

The application deliberately shows *how* a number was produced and whether it
can be trusted, instead of presenting a conclusion. Three rules shape it:

1. **A run is a first-class object.** Every figure on screen belongs to exactly
   one immutable run, with a manifest recording parameters, fingerprinted
   inputs and outputs. There are no orphan numbers.
2. **Evidence badges are computed, not decorative.** Each badge corresponds to a
   way this model has been observed to mislead (missing market factor,
   in-sample self-check, short sample).
3. **The web UI is only an entry point.** A run started here executes the very
   same ``scripts/run_risk_pipeline.py`` CLI, so a browser run and a terminal
   run are indistinguishable.

Run::

    venv/bin/python -m uvicorn workbench.app:app --port 8090
"""

from __future__ import annotations

import sys
from pathlib import Path

from fastapi import Body, FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from workbench import analytics, runstore  # noqa: E402

STATIC_DIR = Path(__file__).resolve().parent / "static"

app = FastAPI(
    title="AlphaStream Workbench",
    description="风险模型观测台：复现、校准、风险透视与对账",
    version="0.1.0",
)


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/health")
def health() -> dict:
    return {
        "status": "ok",
        "runs_dir": str(runstore.RUNS_DIR),
        "runner": str(runstore.RUNNER),
        "runner_present": runstore.RUNNER.exists(),
        "python": runstore._python(),
    }


@app.get("/api/runs")
def list_runs() -> dict:
    return {"runs": runstore.list_runs()}


@app.post("/api/runs")
def create_run(payload: dict = Body(...)) -> JSONResponse:
    try:
        created = runstore.start_run(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileExistsError as exc:
        raise HTTPException(status_code=409, detail=f"run exists: {exc}") from exc
    return JSONResponse(created, status_code=202)


@app.get("/api/runs/{run_id}")
def get_run(run_id: str) -> dict:
    try:
        return runstore.get_run(run_id)
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=404, detail=f"run not found: {run_id}") from exc


@app.get("/api/runs/{run_id}/log")
def get_log(run_id: str, lines: int = 60) -> dict:
    try:
        return {"run_id": run_id, "lines": runstore.tail_log(run_id, lines)}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/runs/{run_id}/calibration")
def get_calibration(run_id: str) -> dict:
    try:
        return analytics.calibration(run_id)
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=404, detail=f"run has no self-check report: {run_id}"
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/api/runs/{run_id}/risk")
def get_risk(run_id: str, scheme: str = "equal") -> dict:
    try:
        return analytics.risk_view(run_id, scheme)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=404, detail=f"run is missing an artifact: {exc}"
        ) from exc


@app.get("/api/runs/{run_id}/evidence")
def get_evidence(run_id: str) -> dict:
    try:
        return {"run_id": run_id, "badges": analytics.evidence(run_id)}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/runs/{run_id}/artifact/{name}")
def get_artifact(run_id: str, name: str) -> FileResponse:
    try:
        path = runstore.artifact_path(run_id, name)
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=404, detail=f"artifact not found: {name}") from exc
    return FileResponse(path, filename=f"{run_id}__{name}")


@app.get("/api/compare")
def get_compare(left: str, right: str) -> dict:
    try:
        return analytics.compare(left, right)
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
