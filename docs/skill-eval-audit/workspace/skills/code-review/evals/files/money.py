from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP


@dataclass(frozen=True)
class Money:
    """An amount in minor units (cents) for a single currency."""

    cents: int
    currency: str = "EUR"

    @classmethod
    def from_decimal(cls, value: Decimal | str, currency: str = "EUR") -> "Money":
        amount = Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        return cls(int(amount * 100), currency)

    def __post_init__(self) -> None:
        if not self.currency:
            raise ValueError("currency is required")

    def add(self, other: "Money") -> "Money":
        self._check_currency(other)
        return Money(self.cents + other.cents, self.currency)

    def subtract(self, other: "Money") -> "Money":
        self._check_currency(other)
        return Money(self.cents - other.cents, self.currency)

    def percentage(self, percent: Decimal | str) -> "Money":
        factor = Decimal(percent) / Decimal(100)
        cents = (Decimal(self.cents) * factor).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        return Money(int(cents), self.currency)

    def _check_currency(self, other: "Money") -> None:
        if other.currency != self.currency:
            raise ValueError(f"currency mismatch: {self.currency} vs {other.currency}")

    def __str__(self) -> str:
        return f"{self.cents / 100:.2f} {self.currency}"
