"""Orders and fills: what a strategy asks for, and what the broker did."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class Side(int, Enum):
    BUY = 1
    SELL = -1


class OrderType(str, Enum):
    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"


@dataclass
class Order:
    instrument: str
    side: Side
    quantity: float
    type: OrderType = OrderType.MARKET
    limit_price: float | None = None
    stop_price: float | None = None
    tag: str = ""  # free text from the strategy, shown in the trade log
    parent: str | None = None  # bracket orders point at their entry
    id: str = ""


@dataclass
class Fill:
    order_id: str
    instrument: str
    time: datetime
    side: Side
    quantity: float
    price: float
    cost: float  # spread, slippage and commission, in account currency
    info: dict[str, Any] = field(default_factory=dict)
