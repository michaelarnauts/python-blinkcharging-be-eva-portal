"""Simple usage example: print the current state of your charger(s).

python examples/dump.py
"""

from __future__ import annotations

import asyncio
import os

from dotenv import load_dotenv

from blinkcharging_be_eva_portal import BlinkChargingClient


async def main() -> None:
    load_dotenv()
    user = os.environ["BLINKCHARGING_USERNAME"]
    pw = os.environ["BLINKCHARGING_PASSWORD"]

    async with BlinkChargingClient(user, pw) as client:
        snap = await client.async_get_snapshot()
        print(f"Signed in as {snap['user'].email}")
        for cp in snap["charge_points"].values():
            print(f"\n{cp.public_identifier or cp.id}  ({cp.vendor} {cp.charger_type})")
            print(f"  online: {cp.online_state}   state: {cp.state}")
            for conn in cp.connectors:
                print(
                    f"  connector #{conn.number}: state={conn.state} detail={conn.state_detail} "
                    f"meter={conn.last_meter_value_wh} Wh"
                )
                if conn.active_session:
                    s = conn.active_session
                    print(
                        f"    session {s.id}: {s.consumption_wh} Wh consumed, "
                        f"{s.current_speed_w} W live, started {s.session_start}"
                    )


if __name__ == "__main__":
    asyncio.run(main())
