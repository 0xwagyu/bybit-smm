
from numba import njit, float64


@njit(float64(float64, float64))
def bba_imbalance(bid: float, ask: float) -> float:
    """
    Imbalance between bid and ask quantities
    """

    return ((bid/(ask + bid)) - 0.5) * 2
