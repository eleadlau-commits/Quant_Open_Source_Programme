"""Orders and fills: what a strategy asks for, and what the broker did."""
from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


_ids = itertools.count(1)


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
    # additions (Phase 1B)
    offset: float | None = None  # bracket exit: distance from the entry's fill price (instead of a fixed price)
    expires: datetime | None = None  # cancelled if not filled before this time
    reduce_only: bool = False  # may only shrink a position (bracket exits are always reduce-only)


def bracket(instrument: str, side: Side | int, quantity: float, *, stop: float | None = None,
            target: float | None = None, stop_offset: float | None = None, target_offset: float | None = None,
            entry: OrderType = OrderType.MARKET, entry_price: float | None = None, tag: str = "",
            id: str = "") -> list[Order]:
    """An entry with a protective stop and/or a profit target, as one list of orders.

    Give exit prices either as levels (``stop=``, ``target=``) or as distances from the
    entry's actual fill price (``stop_offset=``, ``target_offset=``). The exits become
    active once the entry fills; when one of them fills the other is cancelled. If one
    bar touches both, the simulator takes the stop.
    """
    side = Side(side)
    entry_id = id or f"b{next(_ids)}"
    out = [Order(instrument, side, quantity, entry, limit_price=entry_price if entry is OrderType.LIMIT else None,
                 stop_price=entry_price if entry is OrderType.STOP else None, tag=tag, id=entry_id)]
    exit_side = Side(-side)
    if stop is not None or stop_offset is not None:
        out.append(Order(instrument, exit_side, quantity, OrderType.STOP, stop_price=stop, offset=stop_offset,
                         tag=tag or "stop", parent=entry_id, id=f"{entry_id}.stop", reduce_only=True))
    if target is not None or target_offset is not None:
        out.append(Order(instrument, exit_side, quantity, OrderType.LIMIT, limit_price=target, offset=target_offset,
                         tag=tag or "target", parent=entry_id, id=f"{entry_id}.target", reduce_only=True))
    return out


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
