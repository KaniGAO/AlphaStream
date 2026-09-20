"""AlphaStream Workbench -- a risk-model observatory.

Modules
-------
- ``runstore``  : discover, inspect and launch pipeline runs
- ``analytics`` : derived views (calibration, risk, evidence badges, compare)
- ``app``       : FastAPI application + static single-page UI

Everything the workbench shows is derived from immutable runs under
``runs/<run_id>/``; the UI never invents a number and never runs a second
implementation of the pipeline.
"""
