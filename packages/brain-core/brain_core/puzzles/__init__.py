"""Puzzle models from Hürlimann, Puzzles and Games: A Mathematical
Modeling Approach (6th ed. 2025), built on CP-SAT with The-brain's
honest-status conventions."""

from .chess import knight_domination, queen_domination, max_queens  # noqa: F401
from .logic import (  # noqa: F401
    einstein, wolf_goat_cabbage, send_more_money, change_dollar,
)
from .numeric import seven_eleven, golomb_ruler, magic_square, sudoku  # noqa: F401
