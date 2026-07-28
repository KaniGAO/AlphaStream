"""Common contract for raw factor implementations.

This module defines what every factor must provide and validates the shared
input/output rules. It does not contain any concrete factor formula.
"""

from abc import ABC, abstractmethod
from collections.abc import Sequence

import pandas as pd
from pandas.api.types import is_datetime64_any_dtype, is_numeric_dtype


class Factor(ABC):
    """Base contract for raw factor implementations.

    Input contract
    --------------
    ``panel`` must be a ``pandas.DataFrame`` with a two-level
    ``pandas.MultiIndex`` named exactly ``["Date", "Ticker"]``.

    Each ``(Date, Ticker)`` pair must uniquely identify one observation.
    The ``Date`` level must contain datetime-like values. The panel must
    include every column declared in the factor's ``required_columns``.

    Output contract
    ---------------
    ``compute()`` returns a ``pandas.Series`` containing raw factor
    exposures. Its index must exactly equal the input panel index, including
    values, level names, and order. Its name must equal the factor's ``name``.

    Exposure values must have a numeric dtype. Missing or insufficient input
    data must remain ``NaN`` and must not be silently filled with zero.

    Point-in-time contract
    ----------------------
    An exposure calculated for date ``t`` may only use information available
    on or before ``t``.

    Prices, volume, and rolling statistics must not use observations after
    ``t``. Fundamental descriptors must be aligned by their effective or
    availability date and must not be backfilled into periods before the
    information became available.

    Responsibility boundary
    -----------------------
    A factor subclass is responsible only for calculating one factor's raw,
    point-in-time exposure from the standard panel.

    Cross-sectional winsorization, z-score standardization, industry
    neutralization, and cross-factor orthogonalization belong in
    ``transforms.py``. Factor orchestration, ``as_of`` filtering, exposure
    assembly, and final matrix generation belong in ``pipeline.py``.
    """

    name: str
    required_columns: Sequence[str] = ()

    def compute(self, panel: pd.DataFrame) -> pd.Series:
        """Calculate a raw exposure through the validated public interface.

        Subclasses implement only :meth:`_compute`. This template method
        applies the common input and output checks to every factor.
        """
        self.validate_input(panel)
        exposure = self._compute(panel)
        self.validate_output(panel, exposure)
        return exposure

    def validate_input(self, panel: pd.DataFrame) -> None:
        """Validate that ``panel`` satisfies the shared input contract.

        This method validates but never sorts, fills, or otherwise mutates the
        supplied panel.
        """
        if not isinstance(panel, pd.DataFrame):
            raise TypeError(
                "panel must be a pandas DataFrame, "
                f"got {type(panel).__name__}"
            )

        if not isinstance(panel.index, pd.MultiIndex):
            raise ValueError(
                "panel index must be a pandas MultiIndex with levels "
                "['Date', 'Ticker']"
            )

        expected_index_names = ["Date", "Ticker"]
        actual_index_names = list(panel.index.names)
        if actual_index_names != expected_index_names:
            raise ValueError(
                f"panel index names must be {expected_index_names}, "
                f"got {actual_index_names}"
            )

        date_level = panel.index.get_level_values("Date")
        if not is_datetime64_any_dtype(date_level.dtype):
            raise ValueError(
                "the Date index level must be datetime-like, "
                f"got dtype {date_level.dtype}"
            )

        if panel.index.has_duplicates:
            duplicate_count = int(panel.index.duplicated(keep=False).sum())
            raise ValueError(
                "panel index must contain unique (Date, Ticker) pairs; "
                f"found {duplicate_count} rows belonging to duplicate pairs"
            )

        missing_columns = sorted(
            set(self.required_columns) - set(panel.columns)
        )
        if missing_columns:
            raise ValueError(
                f"{type(self).__name__} requires columns "
                f"{list(self.required_columns)}, "
                f"but panel is missing {missing_columns}"
            )

    def validate_output(
        self,
        panel: pd.DataFrame,
        exposure: pd.Series,
    ) -> None:
        """Validate a raw exposure returned by a factor implementation."""
        if not isinstance(exposure, pd.Series):
            raise TypeError(
                "exposure must be a pandas Series, "
                f"got {type(exposure).__name__}"
            )

        if not exposure.index.equals(panel.index):
            raise ValueError(
                "exposure index must exactly match the panel index, "
                "including values, level names, and order"
            )

        if exposure.name != self.name:
            raise ValueError(
                f"exposure name must be {self.name!r}, "
                f"got {exposure.name!r}"
            )

        if not is_numeric_dtype(exposure.dtype):
            raise TypeError(
                "exposure values must have a numeric dtype, "
                f"got {exposure.dtype}"
            )

    @abstractmethod
    def _compute(self, panel: pd.DataFrame) -> pd.Series:
        """Calculate this factor's raw point-in-time exposure."""
        raise NotImplementedError
