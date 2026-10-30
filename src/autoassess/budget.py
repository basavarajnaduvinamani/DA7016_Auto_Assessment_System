"""Spend ledgers and guards for paid providers.

Each paid provider keeps a running total next to the cache. A call is refused
once the total reaches its budget, so a loop or a leaked demo link can never
spend more than the limit. Cached calls cost nothing and are never counted.

- OpenRouter: the exact cost from each response's `usage.cost`, in USD.
- Bodhan: the published price per page or per output token, in rupees.
"""

from __future__ import annotations

import json
from pathlib import Path


class BudgetExceeded(RuntimeError):
    """A paid operation would exceed the configured provider budget."""

    pass


class Ledger:
    """Running spend for one provider, kept as JSON beside the cache."""

    def __init__(self, path: Path, budget: float | None, currency: str = "inr", budget_var: str = "BODHAN_BUDGET_INR"):
        self.path = Path(path)
        self.budget = budget
        self.currency = currency
        self.budget_var = budget_var

    @property
    def symbol(self) -> str:
        """Return the display prefix for this ledger's currency."""
        return "$" if self.currency == "usd" else "Rs "

    def _read(self) -> dict:
        if not self.path.exists():
            return {}
        text = self.path.read_text()
        return json.loads(text) if text.strip() else {}

    def spent(self) -> float:
        """Read the provider's cumulative recorded spend."""
        return float(self._read().get(f"spent_{self.currency}", 0.0))

    def calls(self) -> int:
        """Read the number of paid calls recorded in the ledger."""
        return int(self._read().get("calls", 0))

    def check(self, cost: float = 0.0) -> None:
        """Raise BudgetExceeded if the proposed cost would cross the budget."""
        if self.budget is not None and self.spent() + cost > self.budget + 1e-9:
            raise BudgetExceeded(
                f"budget of {self.symbol}{self.budget:g} reached (spent {self.symbol}{self.spent():.2f}); "
                f"raise {self.budget_var} to continue"
            )

    def add(self, cost: float) -> None:
        # Several grading processes can share one ledger: lock, then replace the file atomically.
        """Record a paid call under a process-shared file lock."""
        import fcntl
        import os

        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path.with_suffix(".lock"), "w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            data = self._read()
            data[f"spent_{self.currency}"] = round(float(data.get(f"spent_{self.currency}", 0.0)) + cost, 6)
            data["calls"] = int(data.get("calls", 0)) + 1
            tmp = self.path.with_suffix(f".{os.getpid()}.tmp")
            tmp.write_text(json.dumps(data))
            os.replace(tmp, self.path)

    def summary(self) -> str:
        """Format current spend, budget and paid-call count for display."""
        budget = f" of {self.symbol}{self.budget:g}" if self.budget is not None else ""
        return f"{self.symbol}{self.spent():.2f}{budget} ({self.calls()} paid calls)"


def bodhan_ledger(cache_dir: Path, budget_inr: float | None) -> Ledger:
    """Create a rupee-denominated ledger for Bodhan calls."""
    return Ledger(Path(cache_dir) / "bodhan_ledger.json", budget_inr, "inr", "BODHAN_BUDGET_INR")


def openrouter_ledger(cache_dir: Path, budget_usd: float | None) -> Ledger:
    """Create a dollar-denominated ledger for OpenRouter calls."""
    return Ledger(Path(cache_dir) / "openrouter_ledger.json", budget_usd, "usd", "OPENROUTER_BUDGET_USD")


def record_llm_cost(ledger: Ledger | None, response: dict) -> None:
    """Add a chat response's billed cost (OpenRouter reports it as usage.cost)."""
    if ledger is None:
        return
    cost = (response.get("usage") or {}).get("cost")
    if cost:
        ledger.add(float(cost))
