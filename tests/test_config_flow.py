"""Tests für den Config Flow."""

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.finanzcockpit.const import DOMAIN


async def test_einrichtung(hass: HomeAssistant, daten_verzeichnis) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Finanzcockpit"
    assert result["options"] == {"dashboard": True}


async def test_dateien_fehlen(hass: HomeAssistant, tmp_path) -> None:
    hass.config.config_dir = str(tmp_path)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "ungueltige_daten"}
    assert "Datei fehlt" in result["description_placeholders"]["fehler"]
