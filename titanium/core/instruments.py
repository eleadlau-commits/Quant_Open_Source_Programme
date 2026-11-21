"""Instruments: the things a strategy can hold."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class InstrumentKind(str, Enum):
    STOCK = "stock"
    FUTURE = "future"
    # later: CRYPTO, FX, OPTION ... added as new kinds, never by changing the engine


@dataclass(frozen=True)
class Instrument:
    symbol: str
    kind: InstrumentKind
    market: str  # Market.id
    currency: str = "USD"
    tick_size: float = 0.01
    multiplier: float = 1.0  # value of one point per unit held (MNQ: 2.0, stocks: 1.0)
    lot_size: float = 1.0  # smallest tradable amount (shares, contracts)
    name: str = ""

    @property
    def key(self) -> str:
        return f"{self.market}:{self.symbol}"
