"""End-to-end risk pipeline runner: X -> r -> f -> F -> D -> Sigma.

Every parameter is an explicit CLI argument and every artifact plus a run
manifest is persisted, so a collaborator on another machine can re-run the
identical configuration and compare numbers.

Usage
-----
    python scripts/run_risk_pipeline.py --out-dir runs/selfcheck-60-120-none

Why this script exists
----------------------
The "vol self-check rel-error median ~24%" figure quoted in commit f54c476 was
produced by an ad-hoc script that was never committed and never persisted its
parameters or outputs, so nobody (including the author, after the
barra_research data directory moved) could reproduce it. This runner is the
missing piece: same code path, explicit parameters, persisted results.
"""

from __future__ import annotations

import argparse
import importlib.metadata as md
import json
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from Data.build_panel import BARRA_ROOT, RETURNS_PATH  # noqa: E402
from risk import (  # noqa: E402
    asset_covariance,
    estimate_factor_covariance,
    estimate_factor_returns,
    estimate_specific_variance,
    load_exposures,
    load_returns,
    risk_decomposition,
    volatility_selfcheck,
)
from risk.exposures import aligned_panel, latest_cross_section  # noqa: E402


def _versions() -> dict[str, str]:
    out = {"python": platform.python_version(), "platform": platform.platform()}
    for pkg in ("numpy", "pandas", "scipy", "scikit-learn", "pyarrow"):
        try:
            out[pkg] = md.version(pkg)
        except md.PackageNotFoundError:  # pragma: no cover
            out[pkg] = "not installed"
    return out


def _git_rev() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except Exception:  # pragma: no cover
        return "unknown"


def _min_eigenvalue(matrix: np.ndarray) -> float:
    return float(np.linalg.eigvalsh((matrix + matrix.T) / 2).min())


def _describe_file(path: Path) -> dict:
    if not path.exists():
        return {"path": str(path), "exists": False}
    stat = path.stat()
    return {
        "path": str(path),
        "exists": True,
        "size_bytes": stat.st_size,
        "modified_utc": datetime.fromtimestamp(
            stat.st_mtime, tz=timezone.utc
        ).isoformat(timespec="seconds"),
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--out-dir",
        type=Path,
        default=None,
        help="Where to write artifacts (default: runs/selfcheck-<w>-<mh>-<shr>)",
    )
    p.add_argument("--window", type=int, default=60,
                   help="Rolling realized-vol window in trading days (default 60)")
    p.add_argument("--min-history", type=int, default=120,
                   help="Days skipped at the start of the self-check (default 120)")
    p.add_argument(
        "--specific-shrinkage",
        choices=("none", "diagonal"),
        default="none",
        help="Shrinkage for the specific-variance diagonal D (default none)",
    )
    p.add_argument("--factor-shrinkage", choices=("ledoit-wolf", "sample"),
                   default="ledoit-wolf")
    p.add_argument("--exposures", type=Path, default=None,
                   help="Override the exposures.parquet path")
    p.add_argument("--returns", type=Path, default=None,
                   help="Override the raw tr panel parquet path")
    p.add_argument("--label", default=None, help="Free-text label stored in the manifest")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    out_dir = args.out_dir or Path(
        f"runs/selfcheck-w{args.window}-mh{args.min_history}-{args.specific_shrinkage}"
    )
    out_dir = (PROJECT_ROOT / out_dir) if not out_dir.is_absolute() else out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 72)
    print("AlphaStream risk pipeline (X -> r -> f -> F -> D -> Sigma)")
    print("=" * 72)
    print(f"barra data root : {BARRA_ROOT}")
    print(f"output dir      : {out_dir}")
    print(f"parameters      : window={args.window} min_history={args.min_history} "
          f"specific_shrinkage={args.specific_shrinkage} "
          f"factor_shrinkage={args.factor_shrinkage}")

    # --- 1. X ---------------------------------------------------------------
    exposures = load_exposures(args.exposures) if args.exposures else load_exposures()
    x_dates = exposures.index.get_level_values("Date")
    print(f"\n[1/6] X : {exposures.shape[0]:,} rows x {exposures.shape[1]} factors | "
          f"{exposures.index.get_level_values('Ticker').nunique()} tickers | "
          f"{x_dates.min():%Y-%m-%d} -> {x_dates.max():%Y-%m-%d}")

    # --- 2. r ---------------------------------------------------------------
    returns = load_returns(exposures=exposures, path=args.returns)
    x_clean, r_clean = aligned_panel(exposures, returns)
    print(f"[2/6] r : {int(r_clean['r'].notna().sum()):,} non-NaN daily returns aligned to X "
          f"| complete cross-sections: {x_clean.index.get_level_values('Date').nunique()} dates")

    # --- 3. f, eps ----------------------------------------------------------
    factor_returns, idio_returns = estimate_factor_returns(x_clean, r_clean)
    valid_days = int(factor_returns.notna().all(axis=0).sum())
    print(f"[3/6] f : {factor_returns.shape[0]} factors x {factor_returns.shape[1]} dates "
          f"({valid_days} fully estimated)")

    # --- 4. F, D ------------------------------------------------------------
    factor_cov = estimate_factor_covariance(
        factor_returns, shrinkage=args.factor_shrinkage
    )
    specific_var = estimate_specific_variance(
        idio_returns, shrinkage=args.specific_shrinkage
    )
    f_min_eig = _min_eigenvalue(factor_cov.to_numpy(dtype=float))
    d_diag = np.diag(specific_var.to_numpy(dtype=float))
    print(f"[4/6] F : {factor_cov.shape}, min eigenvalue = {f_min_eig:.6g} "
          f"({'PD ✅' if f_min_eig > 0 else 'NOT PD ❌'})")
    print(f"      D : {specific_var.shape} diagonal, "
          f"min specific variance = {d_diag.min():.6g} "
          f"({'all positive ✅' if d_diag.min() > 0 else 'NON-POSITIVE ❌'})")

    # --- 5. Sigma + decomposition ------------------------------------------
    as_of = x_dates.max()
    x_t = latest_cross_section(x_clean, as_of)
    # ``estimate_specific_variance`` returns D indexed by every ticker that ever
    # entered the regression, while ``X_t`` only holds the tickers present on
    # ``as_of``. Align D to this cross-section using the same convention as
    # ``volatility_selfcheck`` (missing tickers get zero specific variance);
    # ``asset_covariance`` does not align automatically.
    d_t = specific_var.reindex(index=x_t.index, columns=x_t.index).fillna(0.0)
    sigma = asset_covariance(x_t, factor_cov, d_t)
    s_min_eig = _min_eigenvalue(sigma.to_numpy(dtype=float))
    weights = pd.Series(1.0 / len(x_t), index=x_t.index)
    decomposition = risk_decomposition(weights, x_t, factor_cov, d_t)
    print(f"[5/6] Sigma @ {pd.Timestamp(as_of):%Y-%m-%d}: {sigma.shape}, "
          f"min eigenvalue = {s_min_eig:.6g} "
          f"({'PD ✅' if s_min_eig > 0 else 'NOT PD ❌'})")
    print(f"      equal-weight decomposition: factor {decomposition['factor_pct']:.1%} / "
          f"specific {decomposition['specific_pct']:.1%} | "
          f"annualized vol {decomposition['portfolio_vol_annualized']:.2%}")

    # --- 6. self-check ------------------------------------------------------
    report = volatility_selfcheck(
        x_clean,
        factor_cov,
        specific_var,
        r_clean,
        window=args.window,
        min_history=args.min_history,
    )
    rel = report["rel_error_mean"].dropna()
    median_rel = float(rel.median())
    mean_rel = float(rel.mean())
    print(f"[6/6] self-check: {len(report)} effective check dates "
          f"({report.index.min():%Y-%m-%d} -> {report.index.max():%Y-%m-%d})")
    print(f"      relative error  median = {median_rel:.2%} | mean = {mean_rel:.2%}")

    # --- persist ------------------------------------------------------------
    factor_returns.to_parquet(out_dir / "factor_returns.parquet")
    idio_returns.to_parquet(out_dir / "idio_returns.parquet")
    factor_cov.to_parquet(out_dir / "factor_cov.parquet")
    specific_var.to_parquet(out_dir / "specific_variance.parquet")
    sigma.to_parquet(out_dir / "asset_covariance_latest.parquet")
    report.to_csv(out_dir / "selfcheck_report.csv")

    manifest = {
        "label": args.label,
        "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "git_rev": _git_rev(),
        "versions": _versions(),
        "parameters": {
            "window": args.window,
            "min_history": args.min_history,
            "specific_shrinkage": args.specific_shrinkage,
            "factor_shrinkage": args.factor_shrinkage,
        },
        "inputs": {
            "exposures": _describe_file(
                args.exposures or (PROJECT_ROOT / "Data/Processed/exposures.parquet")
            ),
            "returns": _describe_file(args.returns or RETURNS_PATH),
            "barra_root": str(BARRA_ROOT),
        },
        "shapes": {
            "X": list(exposures.shape),
            "X_complete_rows": int(x_clean.shape[0]),
            "r_non_nan": int(r_clean["r"].notna().sum()),
            "factor_returns": list(factor_returns.shape),
            "F": list(factor_cov.shape),
            "D": list(specific_var.shape),
            "Sigma": list(sigma.shape),
        },
        "checks": {
            "F_min_eigenvalue": f_min_eig,
            "F_positive_definite": bool(f_min_eig > 0),
            "D_min_specific_variance": float(d_diag.min()),
            "D_all_positive": bool(d_diag.min() > 0),
            "Sigma_min_eigenvalue": s_min_eig,
            "Sigma_positive_definite": bool(s_min_eig > 0),
        },
        "selfcheck": {
            "effective_dates": int(len(report)),
            "first_date": str(report.index.min().date()),
            "last_date": str(report.index.max().date()),
            "rel_error_median": median_rel,
            "rel_error_mean": mean_rel,
            "model_vol_mean": float(report["model_vol_mean"].mean()),
            "realized_vol_mean": float(report["realized_vol_mean"].mean()),
        },
        "equal_weight_decomposition": {
            k: (float(v) if isinstance(v, (int, float)) else v)
            for k, v in decomposition.items()
        },
    }
    (out_dir / "run_manifest.json").write_text(json.dumps(manifest, indent=2))

    print(f"\nartifacts written to {out_dir}")
    print(f"manifest: {out_dir / 'run_manifest.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
