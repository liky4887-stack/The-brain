"""Synthetic factories with known-feasible ground truth (Stage 2)."""

from .fnb_factory import (FnbParams, Lot, SyntheticPlant, generate_fnb_factory,
                          verify_ground_truth)

__all__ = ["FnbParams", "Lot", "SyntheticPlant", "generate_fnb_factory",
           "verify_ground_truth"]
