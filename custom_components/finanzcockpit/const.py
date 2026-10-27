"""Konstanten für das Finanzcockpit."""

from datetime import timedelta

DOMAIN = "finanzcockpit"

# Verzeichnis unterhalb von /config, in dem die Daten liegen
DATA_DIR = "finanzcockpit"
KONTEN_FILE = "konten.yaml"
SALDI_FILE = "saldi.csv"
KURSE_FILE = "kurse.csv"
SIMULATION_FILE = "simulation.yaml"

# Wie oft die Dateien neu eingelesen werden
UPDATE_INTERVAL = timedelta(minutes=15)

SERVICE_RELOAD = "reload"

# Gespeicherte Auswahl und Regler-Werte der Simulation
STORE_VERSION = 1
STORE_KEY = f"{DOMAIN}.simulation"
# Zuletzt online geholte Wechselkurse
KURSE_STORE_KEY = f"{DOMAIN}.kurse"
KURSE_INTERVALL = timedelta(hours=6)

# Präfix der Labels, über die Konten einem Topf zugeordnet werden
LABEL_PREFIX = "Topf: "
LABEL_ICON = "mdi:piggy-bank-outline"

# Frontend: JavaScript mit Donut-Karte und Dashboard-Strategie
JS_URL = "/finanzcockpit_static/finanzcockpit.js"

# Optionales Dashboard in der Seitenleiste
CONF_DASHBOARD = "dashboard"
DASHBOARD_URL = "finanzcockpit"
DASHBOARD_TITEL = "Finanzen"
DASHBOARD_ICON = "mdi:finance"
