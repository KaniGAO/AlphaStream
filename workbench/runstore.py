"""Run store: discover, inspect and launch pipeline runs.

A *run* is one immutable execution of ``scripts/run_risk_pipeline.py``. Every
number the workbench displays belongs to exactly one run, and every run writes a
manifest recording its parameters, its inputs (fingerprinted by size and mtime)
and its outputs -- so no figure on screen is ever an orphan.

Layout::

    runs/<run_id>/
        status.json          <- written by the workbench (queued/running/finished)
        run.log              <- combined stdout/stderr of the runner
        run_manifest.json    <- written by the runner: parameters, inputs, checks
        factor_returns.parquet, factor_cov.parquet, specific_variance.parquet,
        asset_covariance_latest.parquet, idio_returns.parquet,
        selfcheck_report.csv
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RUNS_DIR = PROJECT_ROOT / "runs"
RUNNER = PROJECT_ROOT / "scripts" / "run_risk_pipeline.py"
VENV_PYTHON = PROJECT_ROOT / "venv" / "bin" / "python"

STATUS_FILE = "status.json"
MANIFEST_FILE = "run_manifest.json"
LOG_FILE = "run.log"
RESERVED = {STATUS_FILE, MANIFEST_FILE, LOG_FILE}

_RUN_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,80}$")


def _python() -> str:
    return str(VENV_PYTHON) if VENV_PYTHON.exists() else sys.executable


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _read_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def run_dir(run_id: str) -> Path:
    """Resolve a run id to its directory, refusing anything outside RUNS_DIR."""
    if not _RUN_ID_RE.match(run_id or ""):
        raise ValueError(f"invalid run id: {run_id!r}")
    candidate = (RUNS_DIR / run_id).resolve()
    if candidate.parent != RUNS_DIR.resolve():
        raise ValueError(f"invalid run id: {run_id!r}")
    return candidate


def _summarise(run_id: str, directory: Path) -> dict:
    manifest = _read_json(directory / MANIFEST_FILE)
    status = _read_json(directory / STATUS_FILE)
    status = status or {}
    manifest = manifest or {}

    summary = {
        "run_id": run_id,
        "state": status.get("state") or ("finished" if manifest else "unknown"),
        "label": manifest.get("label") or status.get("label"),
        "created_utc": status.get("started_utc") or manifest.get("generated_utc"),
        "git_rev": manifest.get("git_rev"),
        "parameters": manifest.get("parameters") or status.get("parameters"),
        "has_manifest": bool(manifest),
        "artifacts": sorted(
            p.name for p in directory.iterdir() if p.is_file() and p.name not in RESERVED
        ),
    }
    if manifest:
        sc = manifest.get("selfcheck", {})
        summary.update(
            median_rel_error=sc.get("rel_error_median"),
            mean_rel_error=sc.get("rel_error_mean"),
            effective_dates=sc.get("effective_dates"),
            first_date=sc.get("first_date"),
            last_date=sc.get("last_date"),
        )
    if status.get("error"):
        summary["error"] = status["error"]
    return summary


def _is_run(directory: Path) -> bool:
    """A directory counts as a run only if it carries a manifest or a status file.

    ``runs/`` also holds scratch directories (hand-built panels from the
    reconciliation experiments); those are inputs, not runs, and must not
    appear in the run list.
    """
    return (directory / MANIFEST_FILE).exists() or (directory / STATUS_FILE).exists()


def list_runs() -> list[dict]:
    """Every run known to the workbench, newest first."""
    if not RUNS_DIR.exists():
        return []
    runs = [
        _summarise(p.name, p) for p in RUNS_DIR.iterdir() if p.is_dir() and _is_run(p)
    ]
    runs.sort(key=lambda r: (r.get("created_utc") or ""), reverse=True)
    return runs


def get_run(run_id: str) -> dict:
    directory = run_dir(run_id)
    if not directory.is_dir():
        raise FileNotFoundError(run_id)
    return {
        "summary": _summarise(run_id, directory),
        "manifest": _read_json(directory / MANIFEST_FILE),
        "status": _read_json(directory / STATUS_FILE),
    }


def artifact_path(run_id: str, name: str) -> Path:
    """Resolve a downloadable file inside the run directory.

    The manifest is downloadable on purpose: exchanging ``run_manifest.json`` is
    how two collaborators reconcile runs, so it must not be walled off.
    """
    directory = run_dir(run_id).resolve()
    target = (directory / name).resolve()
    if target.parent != directory:
        raise ValueError("invalid artifact name")
    if not target.is_file():
        raise FileNotFoundError(name)
    return target


def tail_log(run_id: str, lines: int = 60) -> list[str]:
    path = run_dir(run_id) / LOG_FILE
    if not path.exists():
        return []
    content = path.read_text(errors="replace").splitlines()
    return content[-lines:]


# --------------------------------------------------------------------------- #
# launching
# --------------------------------------------------------------------------- #

_PARAM_SPEC = {
    "window": (int, 5, 500),
    "min_history": (int, 0, 2000),
    "specific_shrinkage": (("none", "diagonal"), None, None),
    "factor_shrinkage": (("ledoit-wolf", "sample"), None, None),
}


def _clean_params(raw: dict) -> dict:
    """Validate and normalise user-supplied parameters (whitelist only)."""
    params = {
        "window": 60,
        "min_history": 120,
        "specific_shrinkage": "none",
        "factor_shrinkage": "ledoit-wolf",
        "exposures": None,
        "returns": None,
        "label": None,
    }
    for key, (kind, low, high) in _PARAM_SPEC.items():
        if key not in raw or raw[key] in (None, ""):
            continue
        value = raw[key]
        if isinstance(kind, tuple):
            if value not in kind:
                raise ValueError(f"{key} must be one of {kind}")
            params[key] = value
        else:
            value = int(value)
            if not (low <= value <= high):
                raise ValueError(f"{key} must be between {low} and {high}")
            params[key] = value

    for key in ("exposures", "returns"):
        value = raw.get(key)
        if value:
            path = Path(value).expanduser().resolve()
            if not path.is_file():
                raise ValueError(f"{key} file not found: {path}")
            params[key] = str(path)

    label = raw.get("label")
    if label:
        params["label"] = str(label)[:200]
    return params


def _new_run_id(params: dict) -> str:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    bits = [
        f"w{params['window']}",
        f"mh{params['min_history']}",
        params["specific_shrinkage"][:4],
    ]
    return f"{stamp}-{'-'.join(bits)}"


def build_command(params: dict, out_dir: Path) -> list[str]:
    """The exact CLI the web UI triggers -- identical to a manual invocation."""
    cmd = [
        _python(),
        str(RUNNER),
        "--out-dir", str(out_dir),
        "--window", str(params["window"]),
        "--min-history", str(params["min_history"]),
        "--specific-shrinkage", params["specific_shrinkage"],
        "--factor-shrinkage", params["factor_shrinkage"],
    ]
    if params.get("label"):
        cmd += ["--label", params["label"]]
    if params.get("exposures"):
        cmd += ["--exposures", params["exposures"]]
    if params.get("returns"):
        cmd += ["--returns", params["returns"]]
    return cmd


def _watch(process: subprocess.Popen, directory: Path) -> None:
    """Write the terminal state once the runner exits."""
    returncode = process.wait()
    status = _read_json(directory / STATUS_FILE) or {}
    status.update(
        state="finished" if returncode == 0 else "failed",
        finished_utc=_now(),
        returncode=returncode,
    )
    if returncode != 0:
        status["error"] = f"runner exited with code {returncode}"
    (directory / STATUS_FILE).write_text(json.dumps(status, indent=2, ensure_ascii=False))


def start_run(raw_params: dict) -> dict:
    """Launch the pipeline runner in the background and track its status."""
    params = _clean_params(raw_params)
    run_id = _new_run_id(params)
    directory = RUNS_DIR / run_id
    if directory.exists():
        raise FileExistsError(run_id)
    directory.mkdir(parents=True)

    command = build_command(params, directory)
    status = {
        "run_id": run_id,
        "state": "running",
        "started_utc": _now(),
        "parameters": params,
        "label": params.get("label"),
        "command": command,
    }
    (directory / STATUS_FILE).write_text(json.dumps(status, indent=2, ensure_ascii=False))

    log = (directory / LOG_FILE).open("w")
    try:
        process = subprocess.Popen(
            command,
            cwd=str(PROJECT_ROOT),
            stdout=log,
            stderr=subprocess.STDOUT,
            text=True,
        )
    except OSError as exc:
        log.close()
        status.update(state="failed", error=str(exc), finished_utc=_now())
        (directory / STATUS_FILE).write_text(
            json.dumps(status, indent=2, ensure_ascii=False)
        )
        raise

    threading.Thread(target=_watch, args=(process, directory), daemon=True).start()
    return {"run_id": run_id, "state": "running", "command": command}
