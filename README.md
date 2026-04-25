# blinkcharging-be-eva-portal

Async Python client for the **Blink Charging Belgium** / **Blue Corner**
customer portal at [eva.blinkcharging.be](https://eva.blinkcharging.be).

The portal talks to `api.bluecorner.be`. This library
logs in with your portal email + password, handles OAuth token refresh,
and exposes the charger + session endpoints you care about as typed
dataclasses.

Async, typed, and suitable for polling clients that want a single
`async_get_snapshot()` call.

> ⚠️ Unofficial. Not affiliated with Blink Charging or Blue Corner.

For endpoint-level reference and sample payloads, see [`docs/API.md`](docs/API.md).

## Install

```bash
pip install blinkcharging-be-eva-portal
```

For local development in this repository:

```bash
pip install -e .
```

## Usage

```python
import asyncio
from blinkcharging_be_eva_portal import BlinkChargingClient

async def main():
    async with BlinkChargingClient("you@example.com", "password") as client:
        user = await client.async_get_user_info()
        chargers = await client.async_get_charge_points()
        for s in chargers:
            cp = await client.async_get_charge_point_minimal(s.id)
            for conn in cp.connectors:
                print(conn.state, conn.active_session)

asyncio.run(main())
```

### One-shot snapshot (HA-style)

```python
snap = await client.async_get_snapshot()
# snap = {"user": UserInfo, "charge_points": {id: ChargePoint, ...}}
```

### CLI

```bash
# Put credentials in .env (copy from .env.example), then:
python -m blinkcharging_be_eva_portal
```

If installed from PyPI, use `pip install blinkcharging-be-eva-portal` first.

## What the API gives you

Per connector (on each charger):

- `state` — `AVAILABLE`, `OCCUPIED`, `CHARGING`, `OFFLINE`, …
- `state_detail` — e.g. `SuspendedEV` (car said no more)
- `session_state` — `PARKING`, `CHARGING`, `FINISHED`
- `power_w`, `current_a`, `voltage_v`, `num_phases` — connector capability
- `last_meter_value_wh` — lifetime cumulative energy (great for HA energy dashboard)
- `active_session` — live `Session` with `consumption_wh` and `current_speed_w` (live power)

Per session:

- `session_start`, `session_end`, `charging_start`, `charging_end`
- `consumption_wh`, `current_speed_w`, `max_speed_w`
- `meter_start`, `meter_end`
