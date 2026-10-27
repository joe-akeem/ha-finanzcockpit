"""Ein Sensor pro Konto."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er, label_registry as lr
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import FinanzcockpitConfigEntry
from .const import DOMAIN, LABEL_ICON, LABEL_PREFIX
from .coordinator import FinanzcockpitCoordinator
from .data import ANLAGEKLASSEN, BASISWAEHRUNG, WAEHRUNGEN, Konto, format_iban
from .entity import SimulationsEntity
from .simulation import Ergebnis


async def async_setup_entry(
    hass: HomeAssistant,
    entry: FinanzcockpitConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    sensoren: list[SensorEntity] = [
        KontoSensor(coordinator, konto) for konto in coordinator.data.konten.values()
    ]
    sensoren.append(TotalSensor(coordinator))
    sensoren += [WaehrungSensor(coordinator, waehrung) for waehrung in WAEHRUNGEN]
    sensoren += [AnlageklasseSensor(coordinator, klasse) for klasse in ANLAGEKLASSEN]
    if coordinator.simulation is not None:
        sensoren += [KennzahlSensor(coordinator, kennzahl) for kennzahl in KENNZAHLEN]
        sensoren += [VerlaufSensor(coordinator), VergleichSensor(coordinator)]
    async_add_entities(sensoren)


class KontoSensor(CoordinatorEntity[FinanzcockpitCoordinator], SensorEntity):
    """Aktueller Saldo eines Kontos in Originalwährung."""

    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_suggested_display_precision = 2

    def __init__(self, coordinator: FinanzcockpitCoordinator, konto: Konto) -> None:
        super().__init__(coordinator)
        self.konto_id = konto.id
        self.entity_id = f"sensor.{DOMAIN}_{konto.id}"
        self._attr_unique_id = f"{DOMAIN}_{konto.id}"
        self._attr_name = konto.name
        self._attr_native_unit_of_measurement = konto.waehrung

    @property
    def _konto(self) -> Konto | None:
        return self.coordinator.data.konten.get(self.konto_id)

    @property
    def available(self) -> bool:
        return super().available and self._konto is not None

    @property
    def native_value(self) -> Decimal | None:
        saldo = self.coordinator.data.aktueller_saldo(self.konto_id)
        return saldo.betrag if saldo else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        konto = self._konto
        if konto is None:
            return {}
        daten = self.coordinator.data
        saldo = daten.aktueller_saldo(self.konto_id)
        return {
            "konto_id": konto.id,
            "topf": konto.topf,
            "anlageklasse": {
                ANLAGEKLASSEN[klasse]: float(anteil * 100)
                for klasse, anteil in konto.anlageklassen.items()
            },
            "wert_chf": float(wert) if (wert := daten.wert_chf(konto.id)) is not None else None,
            "institut": konto.institut,
            "eigentuemer": konto.eigentuemer,
            "land": konto.land,
            "iban": format_iban(konto.iban) if konto.iban else None,
            "rhythmus": konto.rhythmus,
            "stand": saldo.datum.isoformat() if saldo else None,
        }

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._label_zuweisen()

    def _handle_coordinator_update(self) -> None:
        self._label_zuweisen()
        super()._handle_coordinator_update()

    def _label_zuweisen(self) -> None:
        """Weist das Topf-Label zu und entfernt veraltete Topf-Labels."""
        konto = self._konto
        if konto is None or self.registry_entry is None:
            return

        label_reg = lr.async_get(self.hass)
        name = f"{LABEL_PREFIX}{konto.topf}"
        label = label_reg.async_get_label_by_name(name) or label_reg.async_create(
            name, icon=LABEL_ICON
        )

        labels = {
            label_id
            for label_id in self.registry_entry.labels
            if not (
                (vorhanden := label_reg.async_get_label(label_id))
                and vorhanden.name.startswith(LABEL_PREFIX)
            )
        }
        labels.add(label.label_id)
        if labels != self.registry_entry.labels:
            er.async_get(self.hass).async_update_entity(self.entity_id, labels=labels)


class SummenSensor(CoordinatorEntity[FinanzcockpitCoordinator], SensorEntity):
    """Summe über alle Konten in CHF."""

    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_native_unit_of_measurement = BASISWAEHRUNG
    _attr_suggested_display_precision = 0

    def __init__(self, coordinator: FinanzcockpitCoordinator, schluessel: str, name: str) -> None:
        super().__init__(coordinator)
        self.entity_id = f"sensor.{DOMAIN}_summe_{schluessel}"
        self._attr_unique_id = f"{DOMAIN}_summe_{schluessel}"
        self._attr_name = name

    def _anteil(self, wert: Decimal) -> float | None:
        """Anteil am Total in Prozent."""
        total = self.coordinator.data.total_chf()
        return round(float(wert / total * 100), 1) if total else None


class TotalSensor(SummenSensor):
    """Vermögen total."""

    _attr_icon = "mdi:bank"

    def __init__(self, coordinator: FinanzcockpitCoordinator) -> None:
        super().__init__(coordinator, "total", "Vermögen total")

    @property
    def native_value(self) -> Decimal:
        return self.coordinator.data.total_chf()


class WaehrungSensor(SummenSensor):
    """Summe aller Konten einer Währung, umgerechnet in CHF."""

    _attr_icon = "mdi:cash-multiple"

    def __init__(self, coordinator: FinanzcockpitCoordinator, waehrung: str) -> None:
        super().__init__(coordinator, f"waehrung_{waehrung.lower()}", f"Währung {waehrung}")
        self.waehrung = waehrung

    @property
    def native_value(self) -> Decimal:
        return self.coordinator.data.summe_nach_waehrung()[self.waehrung]

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        daten = self.coordinator.data
        kurs = daten.aktueller_kurs(self.waehrung)
        return {
            "anteil": self._anteil(self.native_value),
            "betrag": float(daten.summe_original(self.waehrung)),
            "waehrung": self.waehrung,
            "kurs": float(kurs.kurs) if kurs else 1.0,
            "kurs_stand": kurs.datum.isoformat() if kurs else None,
            "kurs_quelle": kurs.quelle if kurs else None,
        }


class AnlageklasseSensor(SummenSensor):
    """Summe einer Anlageklasse in CHF; gemischte Konten zählen anteilig."""

    _attr_icon = "mdi:chart-pie"

    def __init__(self, coordinator: FinanzcockpitCoordinator, klasse: str) -> None:
        super().__init__(
            coordinator, f"anlageklasse_{klasse}", f"Anlageklasse {ANLAGEKLASSEN[klasse]}"
        )
        self.klasse = klasse

    @property
    def native_value(self) -> Decimal:
        return self.coordinator.data.summe_nach_anlageklasse()[self.klasse]

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"anteil": self._anteil(self.native_value)}


def _runden(wert: float | None, stellen: int = 0) -> float | None:
    return round(wert, stellen) if wert is not None else None


def _prozent(wert: float | None) -> float | None:
    return round(wert * 100, 1) if wert is not None else None


@dataclass(frozen=True)
class Kennzahl:
    """Eine Kennzahl des gewählten Szenarios."""

    schluessel: str
    name: str
    icon: str
    wert: Callable[[Ergebnis], float | int | str | None]
    einheit: str | None = BASISWAEHRUNG
    attribute: Callable[[Ergebnis], dict[str, Any]] = lambda _: {}


KENNZAHLEN = [
    Kennzahl(
        "vorsorgeluecke",
        "Vorsorgelücke pro Monat",
        "mdi:cash-minus",
        lambda e: _runden(e.vorsorgeluecke / 12) if e.vorsorgeluecke is not None else None,
        attribute=lambda e: {
            "jahr": e.beide_pensioniert,
            "renten_pro_jahr": _runden(e.renten_rentnerjahr),
            "ausgaben_pro_jahr": _runden(e.ausgaben_rentnerjahr),
            "heutige_chf": True,
        },
    ),
    Kennzahl(
        "frei_pension_er",
        "Freies Vermögen bei Pension Er",
        "mdi:account-cash",
        lambda e: _runden(e.frei_pension_er),
        attribute=lambda e: {"jahr": e.szenario.pension_er, "heutige_chf": True},
    ),
    Kennzahl(
        "frei_pension_sie",
        "Freies Vermögen bei Pension Sie",
        "mdi:account-cash",
        lambda e: _runden(e.frei_pension_sie),
        attribute=lambda e: {"jahr": e.szenario.pension_sie, "heutige_chf": True},
    ),
    Kennzahl(
        "frei_ende",
        "Freies Vermögen am Ende",
        "mdi:flag-checkered",
        lambda e: _runden(e.frei_ende),
        attribute=lambda e: {"jahr": e.jahre[-1].jahr, "heutige_chf": True},
    ),
    Kennzahl(
        "tiefster_stand",
        "Tiefster Stand freies Vermögen",
        "mdi:arrow-collapse-down",
        lambda e: _runden(e.tiefster_stand),
        attribute=lambda e: {"jahr": e.tiefster_stand_jahr, "heutige_chf": False},
    ),
    Kennzahl(
        "erstes_negatives_jahr",
        "Vermögen aufgebraucht",
        "mdi:alert-circle-outline",
        lambda e: e.erstes_negatives_jahr or "nie",
        einheit=None,
    ),
    Kennzahl(
        "belehnung",
        "Belehnung bei Pension Er",
        "mdi:home-percent",
        lambda e: _prozent(e.belehnung_pension_er),
        einheit=PERCENTAGE,
        attribute=lambda e: {
            "hypothek_pension_er": _runden(e.hypothek_pension_er),
            "hypothek_pension_sie": _runden(e.hypothek_pension_sie),
        },
    ),
    Kennzahl(
        "tragbarkeit",
        "Tragbarkeit im Ruhestand",
        "mdi:scale-balance",
        lambda e: _prozent(e.tragbarkeit),
        einheit=PERCENTAGE,
        attribute=lambda e: {"jahr": e.beide_pensioniert, "erfuellt": e.tragbarkeit_ok},
    ),
    Kennzahl(
        "nettovermoegen_ende",
        "Nettovermögen am Ende",
        "mdi:bank",
        lambda e: _runden(e.nettovermoegen_ende),
        attribute=lambda e: {"jahr": e.jahre[-1].jahr, "heutige_chf": True},
    ),
    Kennzahl(
        "steuern_summe",
        "Steuern total",
        "mdi:receipt-text-outline",
        lambda e: _runden(e.steuern_summe),
        attribute=lambda e: {"heutige_chf": False},
    ),
]


def _warnungen(e: Ergebnis) -> list[str]:
    warnungen = []
    if e.erstes_negatives_jahr:
        warnungen.append(f"Das freie Vermögen wird {e.erstes_negatives_jahr} negativ.")
    if e.tragbarkeit is not None and not e.tragbarkeit_ok:
        warnungen.append("Die Tragbarkeit im Ruhestand ist nicht erfüllt: mehr amortisieren.")
    if not e.sperrfrist_ok:
        warnungen.append("Ein PK-Einkauf liegt weniger als 3 Jahre vor dem Kapitalbezug.")
    return warnungen


class SimulationsSensor(SimulationsEntity, SensorEntity):
    """Sensor mit einem Ergebnis der Simulation."""

    def __init__(self, coordinator: FinanzcockpitCoordinator, schluessel: str, name: str) -> None:
        super().__init__(coordinator, "sensor", schluessel, name)

    @property
    def available(self) -> bool:
        return super().available and self.coordinator.ergebnis is not None


class KennzahlSensor(SimulationsSensor):
    """Kennzahl des gewählten Szenarios mit den Regler-Werten."""

    def __init__(self, coordinator: FinanzcockpitCoordinator, kennzahl: Kennzahl) -> None:
        super().__init__(coordinator, kennzahl.schluessel, kennzahl.name)
        self.kennzahl = kennzahl
        self._attr_icon = kennzahl.icon
        self._attr_native_unit_of_measurement = kennzahl.einheit
        if kennzahl.einheit == BASISWAEHRUNG:
            self._attr_device_class = SensorDeviceClass.MONETARY
            self._attr_suggested_display_precision = 0
        elif kennzahl.einheit == PERCENTAGE:
            self._attr_suggested_display_precision = 1

    @property
    def native_value(self) -> float | int | str | None:
        ergebnis = self.coordinator.ergebnis
        return self.kennzahl.wert(ergebnis) if ergebnis else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        ergebnis = self.coordinator.ergebnis
        return self.kennzahl.attribute(ergebnis) if ergebnis else {}


class VerlaufSensor(SimulationsSensor):
    """Jahreswerte des gewählten Szenarios für Diagramme; Zustand ist der Szenario-Name."""

    _attr_icon = "mdi:chart-line"
    # Die Jahresliste ist gross und gehört nicht in die Verlaufsdatenbank
    _unrecorded_attributes = frozenset({"jahre"})

    def __init__(self, coordinator: FinanzcockpitCoordinator) -> None:
        super().__init__(coordinator, "verlauf", "Vorsorge-Verlauf")

    @property
    def native_value(self) -> str | None:
        ergebnis = self.coordinator.ergebnis
        return ergebnis.szenario.name if ergebnis else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        e = self.coordinator.ergebnis
        if e is None:
            return {}
        return {
            "szenario_id": e.szenario.id,
            "angepasst": bool(self.coordinator.anpassungen),
            "pension_er": e.szenario.pension_er,
            "pension_sie": e.szenario.pension_sie,
            "beide_pensioniert": e.beide_pensioniert,
            "warnungen": _warnungen(e),
            "jahre": [
                {
                    "jahr": j.jahr,
                    "frei": round(j.frei),
                    "frei_real": round(j.frei_real),
                    "hypothek_real": round(j.hypothek / j.preisindex),
                    "nettovermoegen_real": round(j.nettovermoegen / j.preisindex),
                    "renten_real": round(j.renten_real),
                    "ausgaben_real": round(j.laufende_ausgaben_real),
                }
                for j in e.jahre
            ],
        }


class VergleichSensor(SimulationsSensor):
    """Kennzahlen aller Szenarien aus simulation.yaml (ohne Regler)."""

    _attr_icon = "mdi:compare-horizontal"
    _unrecorded_attributes = frozenset({"szenarien"})

    def __init__(self, coordinator: FinanzcockpitCoordinator) -> None:
        super().__init__(coordinator, "vergleich", "Szenario-Vergleich")

    @property
    def native_value(self) -> int:
        return len(self.coordinator.vergleich)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        aktiv = self.coordinator.aktives_szenario
        return {
            "szenarien": [
                {
                    "id": e.szenario.id,
                    "name": e.szenario.name,
                    "aktiv": e.szenario.id == aktiv,
                    **{k.schluessel: k.wert(e) for k in KENNZAHLEN},
                    "tragbarkeit_ok": e.tragbarkeit_ok,
                    "warnungen": _warnungen(e),
                }
                for e in self.coordinator.vergleich.values()
            ]
        }
