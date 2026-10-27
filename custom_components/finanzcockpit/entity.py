"""Gemeinsame Basis der Simulations-Entitäten."""

from __future__ import annotations

from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import FinanzcockpitCoordinator

SIM_PRAEFIX = "sim_"


class SimulationsEntity(CoordinatorEntity[FinanzcockpitCoordinator]):
    """Entität der Vorsorge-Simulation, z.B. sensor.finanzcockpit_sim_verlauf."""

    def __init__(
        self, coordinator: FinanzcockpitCoordinator, plattform: str, schluessel: str, name: str
    ) -> None:
        super().__init__(coordinator)
        self.entity_id = f"{plattform}.{DOMAIN}_{SIM_PRAEFIX}{schluessel}"
        self._attr_unique_id = f"{DOMAIN}_{SIM_PRAEFIX}{schluessel}"
        self._attr_name = name

    @property
    def available(self) -> bool:
        return super().available and self.coordinator.szenario is not None
