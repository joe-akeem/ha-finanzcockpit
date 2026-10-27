"""Frontend: Donut-Karte, Dashboard-Strategie und das optionale Dashboard.

Das Dashboard wird nicht in der Dashboard-Verwaltung von Home Assistant
gespeichert, sondern wie ein YAML-Dashboard als Panel registriert. Es
besteht nur aus der Strategie «custom:finanzcockpit» und verschwindet
wieder, wenn die Option ausgeschaltet oder die Integration entfernt wird.
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Any

from homeassistant.components import frontend
from homeassistant.components.http import StaticPathConfig
from homeassistant.components.lovelace.const import LOVELACE_DATA, MODE_YAML
from homeassistant.components.lovelace.dashboard import LovelaceConfig
from homeassistant.core import HomeAssistant
from homeassistant.helpers.json import json_bytes, json_fragment

from .const import DASHBOARD_ICON, DASHBOARD_TITEL, DASHBOARD_URL, DOMAIN, JS_URL

_LOGGER = logging.getLogger(__name__)

JS_DATEI = Path(__file__).parent / "frontend" / "finanzcockpit.js"
DASHBOARD_KONFIG = {"strategy": {"type": f"custom:{DOMAIN}"}}


async def async_js_registrieren(hass: HomeAssistant) -> None:
    """Stellt das JavaScript bereit und lädt es in jedem Browser."""
    # Die Prüfsumme im Link sorgt dafür, dass Browser nach einem Update die neue Datei laden
    version = await hass.async_add_executor_job(_pruefsumme, JS_DATEI)
    await hass.http.async_register_static_paths(
        [StaticPathConfig(JS_URL, str(JS_DATEI), cache_headers=True)]
    )
    frontend.add_extra_js_url(hass, f"{JS_URL}?v={version}")


def _pruefsumme(pfad: Path) -> str:
    return hashlib.sha256(pfad.read_bytes()).hexdigest()[:12]


class StrategieDashboard(LovelaceConfig):
    """Dashboard, dessen Inhalt die Strategie im Browser erzeugt."""

    @property
    def mode(self) -> str:
        return MODE_YAML

    async def async_get_info(self) -> dict[str, Any]:
        return {"mode": self.mode, "views": 0}

    async def async_load(self, force: bool) -> dict[str, Any]:
        return DASHBOARD_KONFIG

    async def async_json(self, force: bool) -> json_fragment:
        return json_fragment(json_bytes(DASHBOARD_KONFIG))


def async_dashboard_anlegen(hass: HomeAssistant) -> None:
    """Zeigt das Dashboard «Finanzen» in der Seitenleiste."""
    dashboards = hass.data[LOVELACE_DATA].dashboards
    if DASHBOARD_URL in dashboards:
        if not isinstance(dashboards[DASHBOARD_URL], StrategieDashboard):
            _LOGGER.warning(
                "Es gibt bereits ein Dashboard unter /%s, das Finanzcockpit legt keines an",
                DASHBOARD_URL,
            )
        return

    dashboards[DASHBOARD_URL] = StrategieDashboard(
        hass,
        DASHBOARD_URL,
        {
            "mode": MODE_YAML,
            "title": DASHBOARD_TITEL,
            "icon": DASHBOARD_ICON,
            "show_in_sidebar": True,
            "require_admin": False,
        },
    )
    frontend.async_register_built_in_panel(
        hass,
        "lovelace",
        sidebar_title=DASHBOARD_TITEL,
        sidebar_icon=DASHBOARD_ICON,
        frontend_url_path=DASHBOARD_URL,
        config={"mode": MODE_YAML},
    )


def async_dashboard_entfernen(hass: HomeAssistant) -> None:
    """Entfernt das Dashboard wieder, sofern es vom Finanzcockpit stammt."""
    dashboards = hass.data[LOVELACE_DATA].dashboards
    if isinstance(dashboards.get(DASHBOARD_URL), StrategieDashboard):
        dashboards.pop(DASHBOARD_URL)
        frontend.async_remove_panel(hass, DASHBOARD_URL)
