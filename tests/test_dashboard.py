"""Tests für Frontend und Dashboard."""

from homeassistant.components.frontend import DATA_EXTRA_MODULE_URL, DATA_PANELS
from homeassistant.components.lovelace.const import LOVELACE_DATA
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.finanzcockpit.const import CONF_DASHBOARD, DASHBOARD_URL, DOMAIN, JS_URL


async def richte_ein(hass: HomeAssistant, dashboard: bool) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN, title="Finanzcockpit", options={CONF_DASHBOARD: dashboard}
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_javascript_wird_geladen(hass: HomeAssistant, daten_verzeichnis) -> None:
    await richte_ein(hass, dashboard=False)

    urls = hass.data[DATA_EXTRA_MODULE_URL].urls
    assert any(url.startswith(f"{JS_URL}?v=") for url in urls)


async def test_dashboard_mit_strategie(hass: HomeAssistant, daten_verzeichnis) -> None:
    await richte_ein(hass, dashboard=True)

    panel = hass.data[DATA_PANELS][DASHBOARD_URL]
    assert panel.sidebar_title == "Finanzen"
    konfig = await hass.data[LOVELACE_DATA].dashboards[DASHBOARD_URL].async_load(False)
    assert konfig == {"strategy": {"type": "custom:finanzcockpit"}}


async def test_ohne_dashboard(hass: HomeAssistant, daten_verzeichnis) -> None:
    await richte_ein(hass, dashboard=False)

    assert DASHBOARD_URL not in hass.data[DATA_PANELS]


async def test_option_blendet_dashboard_aus(hass: HomeAssistant, daten_verzeichnis) -> None:
    entry = await richte_ein(hass, dashboard=True)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_DASHBOARD: False}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options == {CONF_DASHBOARD: False}
    assert DASHBOARD_URL not in hass.data[DATA_PANELS]
    assert DASHBOARD_URL not in hass.data[LOVELACE_DATA].dashboards


async def test_entfernen_raeumt_auf(hass: HomeAssistant, daten_verzeichnis) -> None:
    entry = await richte_ein(hass, dashboard=True)

    await hass.config_entries.async_unload(entry.entry_id)

    assert DASHBOARD_URL not in hass.data[DATA_PANELS]


async def test_frontend_erhaelt_strategie(
    hass: HomeAssistant, daten_verzeichnis, hass_ws_client
) -> None:
    await richte_ein(hass, dashboard=True)
    client = await hass_ws_client(hass)

    await client.send_json_auto_id({"type": "lovelace/config", "url_path": DASHBOARD_URL})
    antwort = await client.receive_json()

    assert antwort["success"]
    assert antwort["result"] == {"strategy": {"type": "custom:finanzcockpit"}}
