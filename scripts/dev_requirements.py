"""Gibt die Python-Pakete aus, die die lokale HA-Instanz braucht.

Das Testpaket installiert Home Assistant ohne die Abhängigkeiten der
einzelnen Komponenten. Manche davon importiert HA aber, bevor es sie
selbst nachinstallieren kann (z.B. beim Laden der Aktionen oder beim
Onboarding). Die Liste wird aus den Manifesten der installierten
HA-Version abgeleitet und passt deshalb immer zur Version.
"""

import json
from pathlib import Path

import homeassistant.components

KOMPONENTEN = [
    # config/configuration.yaml
    "frontend",
    "history",
    "logbook",
    "recorder",
    # Onboarding richtet diese standardmässig ein
    "google_translate",
    "met",
    "radio_browser",
    "shopping_list",
    # Importiert HA beim Laden der Aktionsbeschreibungen (helpers/service.py)
    "ai_task",
    "alarm_control_panel",
    "assist_satellite",
    "calendar",
    "camera",
    "climate",
    "cover",
    "fan",
    "humidifier",
    "light",
    "lock",
    "media_player",
    "notify",
    "remote",
    "siren",
    "todo",
    "update",
    "vacuum",
    "water_heater",
]


def main() -> None:
    basis = Path(homeassistant.components.__file__).parent
    offen, gesehen, pakete = list(KOMPONENTEN), set(), set()
    while offen:
        domain = offen.pop()
        if domain in gesehen:
            continue
        gesehen.add(domain)
        manifest = json.loads((basis / domain / "manifest.json").read_text())
        pakete.update(manifest.get("requirements", []))
        offen += manifest.get("dependencies", []) + manifest.get("after_dependencies", [])
    print("\n".join(sorted(pakete)))


if __name__ == "__main__":
    main()
