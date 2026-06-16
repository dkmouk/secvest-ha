# ABUS Secvest für Home Assistant

Custom Integration zur Anbindung einer ABUS Secvest Alarmanlage an Home Assistant.

Diese Integration ist nicht offiziell von ABUS und nicht mit ABUS verbunden.

Vielen Dank an Jochen aka Birdy aus dem alarmforum.de.
Er hat mir seine Files zur Verfügung gestellt und ich habe seine Ideen hier integriert.

## Funktionen

- Alarmzentrale für Scharf, Teilscharf und Unscharf
- Melder/Zonen als Binary Sensors
- Übersicht offener Melder
- Fault-, Batterie-, Funk- und Sabotage-Diagnose, abhängig von Firmware und Benutzerrechten
- Buttons für Aktualisierung und Fault-Quittierung
- Einrichtung über die Home-Assistant-Oberfläche
- Lokales Polling

## Installation über HACS

1. HACS in Home Assistant öffnen.
2. Zu **Integrationen** wechseln.
3. Drei-Punkte-Menü öffnen und **Benutzerdefinierte Repositories** wählen.
4. Diese Repository-URL eintragen:

   ```text
   https://github.com/dkmouk/secvest-ha
   ```

5. Kategorie **Integration** auswählen.
6. **ABUS Secvest** installieren.
7. Home Assistant neu starten.
8. Integration hinzufügen über **Einstellungen > Geräte & Dienste > Integration hinzufügen > ABUS Secvest**.

## Manuelle Installation

Den Ordner der Integration nach Home Assistant kopieren:

```text
custom_components/secvest/
```

Danach Home Assistant neu starten.

## Konfiguration

Beispiel für den Host:

```text
https://192.168.2.22:4433
```

Bei neueren Secvest-Firmware-Versionen muss im Feld **Benutzername / Code** auch der Benutzer-Code eingetragen werden.

Empfohlene Polling-Werte:

- Status-Intervall: `10` Sekunden
- Melder-/Zonen-Intervall: `10` Sekunden

Wenn die Secvest instabil oder träge reagiert, beide Werte auf `15` oder `30` Sekunden erhöhen.

## Brand-/Logo-Dateien

Für Home Assistant 2026.3 und neuer können lokale Brand-Dateien direkt mitgeliefert werden:

```text
custom_components/secvest/brand/
```

Unterstützte Dateien:

- `icon.png`
- `icon@2x.png`
- `dark_icon.png`
- `dark_icon@2x.png`
- `logo.png`
- `logo@2x.png`
- `dark_logo.png`
- `dark_logo@2x.png`

## Hinweise

Alarmanlagen sind sicherheitsrelevante Systeme. Bitte alle Steuerbefehle, Automationen und Dashboards gründlich testen.

Die Nutzung erfolgt auf eigene Verantwortung.

---

# ABUS Secvest for Home Assistant

Custom integration for connecting an ABUS Secvest alarm system to Home Assistant.

This integration is not official and is not affiliated with ABUS.

Many thanks to Jochen, aka Birdy, from alarmforum.de.
He shared his files with me, and I've incorporated his ideas here.

## Features

- Alarm control panel for arm, part-arm and disarm
- Zone/contact binary sensors
- Open-zone overview
- Fault, battery, RF and tamper diagnostics, depending on firmware and user permissions
- Buttons for refresh and fault acknowledgement
- Setup via the Home Assistant UI
- Local polling

## Installation with HACS

1. Open HACS in Home Assistant.
2. Go to **Integrations**.
3. Open the three-dot menu and choose **Custom repositories**.
4. Add this repository URL:

   ```text
   https://github.com/dkmouk/secvest-ha
   ```

5. Select category **Integration**.
6. Install **ABUS Secvest**.
7. Restart Home Assistant.
8. Add the integration via **Settings > Devices & services > Add integration > ABUS Secvest**.

## Manual Installation

Copy the integration folder to:

```text
custom_components/secvest/
```

Then restart Home Assistant.

## Configuration

Example host:

```text
https://192.168.2.22:4433
```

For newer Secvest firmware versions, the field **Username / Code** also need to contain the user code.

Recommended polling values:

- Status interval: `10` seconds
- Zone/sensor interval: `10` seconds

If your Secvest becomes unstable or slow, increase both values to `15` or `30` seconds.

## Brand Images

For Home Assistant 2026.3 and newer, local brand images can be shipped in:

```text
custom_components/secvest/brand/
```

Supported files:

- `icon.png`
- `icon@2x.png`
- `dark_icon.png`
- `dark_icon@2x.png`
- `logo.png`
- `logo@2x.png`
- `dark_logo.png`
- `dark_logo@2x.png`

## Notes

Alarm systems are safety-relevant devices. Please test all control actions, automations and dashboards carefully.

Use at your own risk.
