"""Figures that can explain themselves.

The rule this package is built around: a number a user cannot explain to an
officer is worse than no number. So a figure here is never a bare integer. It
is an amount plus the means of finding the documents behind it, and the API
never emits one without the other.

**Why a drill is a query and not a list of ids.** The obvious design is for
each figure to carry the ids that make it up. That works for a small shop and
collapses for a busy one: a single B2CS bucket in a month with three thousand
bills would carry three thousand ids, in every figure, in every report. So a
`Drill` describes *how to find* the documents instead - a kind and a filter -
and the drill endpoint resolves it when somebody actually clicks. Small sets
can still pin exact ids by putting them in the filter; large ones stay a
predicate. Either way the figure knows what it is made of.

A figure with an empty drill is allowed, but it is a claim: it says this number
is not derived from documents (a threshold, a constant, a subtotal of figures
that each drill on their own). Anything derived from records carries a drill,
and the cross-checks would rather fail than let one through without.
"""

from dataclasses import dataclass, field
from typing import Any, Optional


class DrillKind:
    """What kind of record lies behind a figure."""

    SALES = "SALES"                  # Sale documents
    SALE_LINES = "SALE_LINES"        # individual outward lines
    PURCHASES = "PURCHASES"          # Invoice documents
    PURCHASE_LINES = "PURCHASE_LINES"
    ITC_REVERSALS = "ITC_REVERSALS"  # ItcReversal ledger rows
    PAYMENTS = "PAYMENTS"            # SalePayment rows

    ALL = {SALES, SALE_LINES, PURCHASES, PURCHASE_LINES, ITC_REVERSALS, PAYMENTS}


@dataclass(frozen=True)
class Drill:
    """How to find the documents behind a figure.

    `filters` is passed to the drill resolver as-is. Recognised keys depend on
    the kind and are documented on the resolver; `ids` is understood by all of
    them and pins an exact set.
    """

    kind: str
    filters: dict = field(default_factory=dict)
    # Known cheaply at aggregation time and worth carrying: the UI shows "4
    # bills" on the number before anybody clicks, which is often all the
    # explanation somebody needed.
    count: Optional[int] = None

    def to_dict(self) -> dict:
        return {"kind": self.kind, "filters": dict(self.filters), "count": self.count}


@dataclass(frozen=True)
class Figure:
    """An amount in integer paise, and where it came from."""

    paise: int
    drill: Optional[Drill] = None
    # Set when the figure is not exact or not authoritative - a purchase-side
    # amount rounded from a stored float, or ITC that GSTR-2B has not yet
    # confirmed. Shown next to the number rather than buried in a footnote.
    caveat: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "paise": self.paise,
            "value": round(self.paise / 100, 2),
            "drill": self.drill.to_dict() if self.drill else None,
            "caveat": self.caveat,
        }

    def __add__(self, other: "Figure") -> "Figure":
        """Adds two figures, keeping any caveat.

        The sum of a certain figure and an uncertain one is uncertain, and the
        caveat has to survive the addition or the doubt disappears exactly
        where it matters most - in the total somebody files. The drill is
        dropped: two different drills do not compose into one, and a wrong
        drill is worse than none.
        """
        caveats = [c for c in (self.caveat, other.caveat) if c]
        return Figure(
            paise=self.paise + other.paise,
            drill=None,
            caveat="; ".join(dict.fromkeys(caveats)) or None,
        )


def figure(paise: int, kind: Optional[str] = None, count: Optional[int] = None,
           caveat: Optional[str] = None, **filters) -> Figure:
    """Convenience constructor: `figure(1200, DrillKind.SALES, period="092026")`."""
    drill = Drill(kind=kind, filters=filters, count=count) if kind else None
    return Figure(paise=paise, drill=drill, caveat=caveat)


def total(figures: Any) -> Figure:
    """Sums figures, preserving caveats. Empty sums to zero, not to nothing."""
    result = Figure(paise=0)
    for item in figures:
        result = result + item
    return result


@dataclass
class CrossCheck:
    """One reconciliation between two figures that must agree.

    Held as a pair rather than a boolean because "these disagree" is not
    useful on its own - the person fixing it needs to know by how much and
    which side to look at. Both sides carry their own drill.
    """

    code: str
    label: str
    left_label: str
    right_label: str
    left: Figure
    right: Figure
    # Some checks legitimately tolerate a gap; most do not. Stated per check
    # rather than assumed, and the reason is in `explanation`.
    tolerance_paise: int = 0
    explanation: str = ""

    @property
    def difference_paise(self) -> int:
        return self.left.paise - self.right.paise

    @property
    def agrees(self) -> bool:
        return abs(self.difference_paise) <= self.tolerance_paise

    def to_dict(self) -> dict:
        return {
            "code": self.code,
            "label": self.label,
            "agrees": self.agrees,
            "difference": round(self.difference_paise / 100, 2),
            "difference_paise": self.difference_paise,
            "tolerance_paise": self.tolerance_paise,
            "explanation": self.explanation,
            "left": {"label": self.left_label, **self.left.to_dict()},
            "right": {"label": self.right_label, **self.right.to_dict()},
        }


@dataclass
class ReportRow:
    """A row of a report: cells, plus the documents behind the row.

    Row-level drill rather than cell-level as the default, because for a
    register the row *is* the document and per-cell drill would be the same
    answer repeated. A cell overrides it by holding a `Figure` with its own
    drill, which is what the aggregate reports do.
    """

    cells: dict
    drill: Optional[Drill] = None
    flags: tuple = ()

    def to_dict(self) -> dict:
        return {
            "cells": {
                key: value.to_dict() if isinstance(value, Figure) else value
                for key, value in self.cells.items()
            },
            "drill": self.drill.to_dict() if self.drill else None,
            "flags": list(self.flags),
        }
