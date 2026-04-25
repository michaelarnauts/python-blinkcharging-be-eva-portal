"""Tiny CLI: dump everything we know about the user's chargers and sessions.

Run with env vars::

    export BLINKCHARGING_USERNAME=...
    export BLINKCHARGING_PASSWORD=...
    python -m blinkcharging_be_eva_portal

A ``.env`` in the current directory is honoured if ``python-dotenv`` is
installed (``pip install blinkcharging-be-eva-portal[dev]``).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from dataclasses import asdict, is_dataclass
from datetime import datetime
from typing import Any

from .client import BlinkChargingClient


def _default(o: Any) -> Any:
    if isinstance(o, datetime):
        return o.isoformat()
    if is_dataclass(o):
        d = asdict(o)
        d.pop("raw", None)  # keep output terse
        return d
    raise TypeError(f"not serialisable: {type(o).__name__}")


async def _run(username: str, password: str, *, verbose: bool) -> int:
    async with BlinkChargingClient(username, password) as client:
        user = await client.async_get_user_info()
        print(
            f"User: {user.first_name} {user.last_name} ({user.email}) [relation {user.relation_id}]"
        )

        summaries = await client.async_get_charge_points()
        print(f"\n{len(summaries)} charger(s):")
        for s in summaries:
            print(f"  • {s.chargeboxidentifier}  id={s.id}  {s.model}  state={s.state}")

        for s in summaries:
            print(f"\n— charger {s.chargeboxidentifier} (id={s.id}) —")
            cp = await client.async_get_charge_point_minimal(s.id)
            for conn in cp.connectors:
                tag = "CHARGING" if conn.is_charging else ("PLUGGED" if conn.is_plugged else "IDLE")
                print(
                    f"  connector #{conn.number} [{tag}] state={conn.state} detail={conn.state_detail} "
                    f"V={conn.voltage_v} A={conn.current_a} phases={conn.num_phases} "
                    f"meter={conn.last_meter_value_wh} Wh"
                )
                if conn.active_session:
                    ses = conn.active_session
                    print(
                        f"    active session id={ses.id} state={ses.state} "
                        f"consumed={ses.consumption_wh} Wh  live={ses.current_speed_w} W  "
                        f"start={ses.session_start}"
                    )

            recent = await client.async_get_recent_sessions(s.id)
            print(f"  last {len(recent)} session(s):")
            for ses in recent[:5]:
                print(
                    f"    {ses.session_start} → {ses.session_end}  "
                    f"{ses.consumption_wh} Wh  state={ses.state}"
                )

        if verbose:
            print("\n--- verbose snapshot ---")
            snap = await client.async_get_snapshot()
            print(json.dumps(snap, default=_default, indent=2, ensure_ascii=False))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Dump Blink Charging data for your account.")
    parser.add_argument("--username", default=os.environ.get("BLINKCHARGING_USERNAME"))
    parser.add_argument("--password", default=os.environ.get("BLINKCHARGING_PASSWORD"))
    parser.add_argument("-v", "--verbose", action="store_true")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging.")
    args = parser.parse_args(argv)

    try:
        from dotenv import load_dotenv  # type: ignore[import-not-found]

        load_dotenv()
        args.username = args.username or os.environ.get("BLINKCHARGING_USERNAME")
        args.password = args.password or os.environ.get("BLINKCHARGING_PASSWORD")
    except ImportError:
        pass

    if args.debug:
        logging.basicConfig(level=logging.DEBUG)
    if not args.username or not args.password:
        parser.error("Need username+password (via args, env vars, or .env file)")
    return asyncio.run(_run(args.username, args.password, verbose=args.verbose))


if __name__ == "__main__":
    sys.exit(main())
