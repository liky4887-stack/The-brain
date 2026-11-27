"""CSV ingestion for canonical factory records (Stage 2, slice 3)."""

from .csv_io import (ERROR_W, WARN_W, Finding, IngestReport, TABLES,
                     dump_csvs, load_csvs)
from .data_report import (DataError, DataErrorReport, SourceRef,
                          build_data_error_report, index_sources)

__all__ = ["ERROR_W", "WARN_W", "Finding", "IngestReport", "TABLES",
           "dump_csvs", "load_csvs", "DataError", "DataErrorReport",
           "SourceRef", "build_data_error_report", "index_sources"]
