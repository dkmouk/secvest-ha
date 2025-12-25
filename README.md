# ABUS Secvest (Home Assistant Custom Integration)

HACS-ready custom integration for ABUS Secvest via local HTTPS API.

## Features
- Alarm control panel (arm home/away, disarm)
- Live zone refresh before arming (prevents stale zone cache)
- Dynamic zone discovery as binary sensors
- Sensors: mode (raw/de), open zones csv/spoken/count, last error
- Retries + circuit breaker for flaky endpoints
- Config flow + options flow

## Install (HACS)
1. HACS → Integrations → ⋮ → Custom repositories
2. Add `https://github.com/dkmouk/secvest-ha` as **Integration**
3. Install and restart Home Assistant

## Disclaimer
Not affiliated with ABUS.
