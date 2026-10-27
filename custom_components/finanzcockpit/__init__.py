"""Finanzcockpit: Kontostände aus YAML/CSV als Sensoren."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType

from .const import CONF_DASHBOARD, DOMAIN, SERVICE_RELOAD
from .coordinator import FinanzcockpitCoordinator
from .dashboard import async_dashboard_anlegen, async_dashboard_entfernen, async_js_registrieren

PLATFORMS = [Platform.BUTTON, Platform.NUMBER, Platform.SELECT, Platform.SENSOR]
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

type FinanzcockpitConfigEntry = ConfigEntry[FinanzcockpitCoordinator]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Registriert die Aktionen und das Frontend."""

    async def _reload(call: ServiceCall) -> None:
        # Ein Neuladen des Eintrags erfasst auch neue oder entfernte Konten
        for entry in hass.config_entries.async_entries(DOMAIN):
            await hass.config_entries.async_reload(entry.entry_id)

    hass.services.async_register(DOMAIN, SERVICE_RELOAD, _reload)
    await async_js_registrieren(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: FinanzcockpitConfigEntry) -> bool:
    """Richtet das Finanzcockpit ein."""
    coordinator = FinanzcockpitCoordinator(hass, entry)
    await coordinator.async_auswahl_laden()
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    if entry.options.get(CONF_DASHBOARD):
        async_dashboard_anlegen(hass)
    entry.async_on_unload(entry.add_update_listener(_optionen_geaendert))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: FinanzcockpitConfigEntry) -> bool:
    """Entfernt das Finanzcockpit."""
    async_dashboard_entfernen(hass)
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _optionen_geaendert(hass: HomeAssistant, entry: FinanzcockpitConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
