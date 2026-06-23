"""Scenario registry. Register new domains here (order = detection precedence)."""
from __future__ import annotations

from .base import Scenario, all_scenarios, get, register, select
from .penalty_delivery import PenaltyDeliveryScenario
from .supplier_pii import SupplierPiiScenario

# Order matters: select() returns the first scenario whose detect() matches.
# The paper §5 scenario is the headline, so it is registered first.
register(PenaltyDeliveryScenario())
register(SupplierPiiScenario())

__all__ = ["Scenario", "all_scenarios", "get", "register", "select"]
