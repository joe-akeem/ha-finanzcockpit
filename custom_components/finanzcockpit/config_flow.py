"""Einrichtung über die Oberfläche."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
import voluptuous as vol

from .const import CONF_DASHBOARD, DATA_DIR, DOMAIN
from .data import FinanzDatenError, lade_daten


class FinanzcockpitConfigFlow(ConfigFlow, domain=DOMAIN):
    """Config Flow: prüft, ob die Dateien vorhanden und gültig sind."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        verzeichnis = Path(self.hass.config.path(DATA_DIR))
        errors: dict[str, str] = {}
        placeholders = {"pfad": str(verzeichnis), "fehler": ""}

        if user_input is not None:
            try:
                await self.hass.async_add_executor_job(lade_daten, verzeichnis)
            except FinanzDatenError as err:
                errors["base"] = "ungueltige_daten"
                placeholders["fehler"] = str(err)
            else:
                return self.async_create_entry(
                    title="Finanzcockpit",
                    data={},
                    options={CONF_DASHBOARD: user_input.get(CONF_DASHBOARD, True)},
                )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({vol.Optional(CONF_DASHBOARD, default=True): bool}),
            errors=errors,
            description_placeholders=placeholders,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return FinanzcockpitOptionsFlow()


class FinanzcockpitOptionsFlow(OptionsFlow):
    """Optionen: Dashboard ein- oder ausblenden."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_DASHBOARD,
                        default=self.config_entry.options.get(CONF_DASHBOARD, False),
                    ): bool
                }
            ),
        )
