"""Gemeinsame Fixtures."""

from pathlib import Path
import shutil

import pytest

from custom_components.finanzcockpit.const import DATA_DIR
from custom_components.finanzcockpit.kurse_online import KRYPTO_URL, KURSE_URL

EXAMPLES = Path(__file__).parent.parent / "examples"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Erlaubt das Laden von custom_components in allen Tests."""
    return


# Online-Kurse in den Tests; älter als die Kurse in examples/kurse.csv
ONLINE_KURSE = {"EUR": 0.9239, "USD": 0.8286}
BITCOIN = 66721
# 2026-10-27 12:00 UTC
BITCOIN_STAND = 1793102400


def online_kurse_mocken(aioclient_mock, datum: str = "2026-10-27", **kurse: float) -> None:
    """Beantwortet die Abfrage der Kurse wie die Frankfurter-API."""
    aioclient_mock.clear_requests()
    for waehrung, kurs in {**ONLINE_KURSE, **kurse}.items():
        aioclient_mock.get(
            KURSE_URL,
            params={"base": waehrung, "symbols": "CHF"},
            json={"amount": 1.0, "base": waehrung, "date": datum, "rates": {"CHF": kurs}},
        )
    aioclient_mock.get(
        KRYPTO_URL,
        params={"ids": "bitcoin", "vs_currencies": "chf", "include_last_updated_at": "true"},
        json={"bitcoin": {"chf": BITCOIN, "last_updated_at": BITCOIN_STAND}},
    )


@pytest.fixture(autouse=True)
def online_kurse(aioclient_mock):
    """Kein Test geht ins Internet."""
    online_kurse_mocken(aioclient_mock)
    return aioclient_mock


@pytest.fixture
def daten_verzeichnis(hass, tmp_path) -> Path:
    """Konfigurationsverzeichnis mit den Beispieldateien."""
    hass.config.config_dir = str(tmp_path)
    verzeichnis = tmp_path / DATA_DIR
    verzeichnis.mkdir()
    shutil.copy(EXAMPLES / "konten.yaml", verzeichnis)
    shutil.copy(EXAMPLES / "saldi.csv", verzeichnis)
    shutil.copy(EXAMPLES / "kurse.csv", verzeichnis)
    shutil.copy(EXAMPLES / "simulation.yaml", verzeichnis)
    shutil.copy(EXAMPLES / "strategie.md", verzeichnis)
    return verzeichnis
