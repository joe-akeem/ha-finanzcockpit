"""Gemeinsame Fixtures."""

from pathlib import Path
import shutil

import pytest

from custom_components.finanzcockpit.const import DATA_DIR

EXAMPLES = Path(__file__).parent.parent / "examples"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Erlaubt das Laden von custom_components in allen Tests."""
    return


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
    return verzeichnis
