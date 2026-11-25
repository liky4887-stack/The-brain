"""Decomposition by plant and time (Stage 4, slice 1)."""

from .parallel import DecomposedResult, solve_decomposed
from .plants import Cell, Partition, partition_plants, sub_factory

__all__ = ["Cell", "DecomposedResult", "Partition", "partition_plants",
           "solve_decomposed", "sub_factory"]
