"""Typed models for the data returned by the Blink Charging portal API.

These are intentionally lenient: the upstream API has many fields we do not
map explicitly. Unknown fields are preserved in the ``raw`` attribute so
callers can still reach them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

BRUSSELS_TZ = ZoneInfo("Europe/Brussels")


def _parse_dt(value: Any) -> datetime | None:
    """Parse the two date formats the API emits.

    - ``"2026-04-24 16:38:09"`` (naive, server-local)
    - ``"2026-04-24T16:38:09+02:00"`` (ISO 8601)
    - empty string / None → None
    """
    if not value:
        return None
    if not isinstance(value, str):
        return None
    try:
        if "T" in value:
            return datetime.fromisoformat(value)
        return datetime.strptime(value, "%Y-%m-%d %H:%M:%S").replace(tzinfo=BRUSSELS_TZ)
    except ValueError:
        return None


def _as_int(value: Any) -> int | None:
    if value in (None, "", 0):
        return 0 if value == 0 else None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _as_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


@dataclass
class Session:
    """A charging session (active or historical)."""

    id: int
    charge_point_id: int | None
    charge_point_name: str | None
    state: str | None
    session_start: datetime | None
    session_end: datetime | None
    charging_start: datetime | None
    charging_end: datetime | None
    consumption_wh: int | None
    current_speed_w: int | None
    max_speed_w: int | None
    meter_start: int | None
    meter_end: int | None
    last_sign_of_life: datetime | None
    evse_id: int | None
    raw: dict[str, Any] = field(repr=False, default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Session:
        return cls(
            id=_as_int(d.get("Id") or d.get("id") or d.get("SessionId")) or 0,
            charge_point_id=_as_int(d.get("ChargePointId")),
            charge_point_name=d.get("ChargePointName") or d.get("chargepointlabel"),
            state=d.get("State"),
            session_start=_parse_dt(
                d.get("SessionStart") or (d.get("ChargeSession") or {}).get("Start")
            ),
            session_end=_parse_dt(d.get("SessionEnd") or (d.get("ChargeSession") or {}).get("End")),
            charging_start=_parse_dt(d.get("ChargingStart")),
            charging_end=_parse_dt(d.get("ChargingEnd")),
            consumption_wh=_as_int(d.get("ConsumptionWh") or d.get("Consumption")),
            current_speed_w=_as_int(d.get("CurrentSpeedW")),
            max_speed_w=_as_int(d.get("MaxSpeedW")),
            meter_start=_as_int(d.get("MeterStart")),
            meter_end=_as_int(d.get("MeterEnd")),
            last_sign_of_life=_parse_dt(d.get("LastSignOfLife")),
            evse_id=_as_int(d.get("EVSEId")),
            raw=d,
        )

    @property
    def is_active(self) -> bool:
        return self.state not in (None, "", "FINISHED", "ENDED", "STOPPED")


@dataclass
class Connector:
    """One physical connector on a charger."""

    id: int
    number: int | None
    state: str | None
    state_detail: str | None
    session_state: str | None
    charging_mode: str | None
    power_w: int | None
    current_a: int | None
    voltage_v: int | None
    num_phases: int | None
    last_meter_value_wh: int | None
    active_session_id: int | None
    active_session: Session | None
    raw: dict[str, Any] = field(repr=False, default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Connector:
        sess_dict = d.get("Session")
        return cls(
            id=_as_int(d.get("Id") or d.get("id")) or 0,
            number=_as_int(d.get("Nr")),
            state=d.get("State"),
            state_detail=d.get("StateDetail"),
            session_state=d.get("SessionState"),
            charging_mode=d.get("ChargingMode"),
            power_w=_as_int(d.get("Power")),
            current_a=_as_int(d.get("Current")),
            voltage_v=_as_int(d.get("Voltage")),
            num_phases=_as_int(d.get("NumPhases")),
            last_meter_value_wh=_as_int(d.get("LastMeterValue")),
            active_session_id=_as_int(d.get("ChargeSessionId")),
            active_session=Session.from_dict(sess_dict) if isinstance(sess_dict, dict) else None,
            raw=d,
        )

    @property
    def is_charging(self) -> bool:
        return self.session_state == "CHARGING" or self.state_detail == "Charging"

    @property
    def is_plugged(self) -> bool:
        return self.state == "OCCUPIED"


@dataclass
class ChargePoint:
    """A physical charger, with its connectors and any active session."""

    id: int
    public_identifier: str | None
    description: str | None
    vendor: str | None
    charger_type: str | None
    model: str | None
    state: str | None
    online_state: str | None
    online_state_datetime: datetime | None
    last_error: str | None
    current_error: str | None
    connectors: list[Connector]
    raw: dict[str, Any] = field(repr=False, default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ChargePoint:
        connectors_raw = d.get("Connectors") or []
        return cls(
            id=_as_int(d.get("Id") or d.get("id")) or 0,
            public_identifier=d.get("PublicIdentifier"),
            description=d.get("Description"),
            vendor=d.get("Vendor"),
            charger_type=d.get("ChargerType"),
            model=d.get("model"),
            state=d.get("State"),
            online_state=d.get("OnlineState"),
            online_state_datetime=_parse_dt(d.get("OnlineStateDateTime")),
            last_error=d.get("LastError"),
            current_error=d.get("CurrentError"),
            connectors=[Connector.from_dict(c) for c in connectors_raw if isinstance(c, dict)],
            raw=d,
        )

    @property
    def is_online(self) -> bool:
        return self.online_state == "ONLINE"

    @property
    def active_session(self) -> Session | None:
        """Return the first connector's active session, if any."""
        for c in self.connectors:
            if c.active_session is not None:
                return c.active_session
        return None


@dataclass
class ChargePointSummary:
    """Lightweight charger info from the ``/chargepoint/BCO/list`` endpoint.

    Enough to identify chargers and their current state without a full
    detail fetch per charger.
    """

    id: int
    chargeboxidentifier: str | None
    model: str | None
    description: str | None
    state: str | None  # Online/Offline/...
    last_heartbeat: datetime | None
    connector_summaries: list[dict[str, Any]]
    raw: dict[str, Any] = field(repr=False, default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ChargePointSummary:
        return cls(
            id=_as_int(d.get("id") or d.get("Id")) or 0,
            chargeboxidentifier=d.get("chargeboxidentifier"),
            model=d.get("model"),
            description=d.get("description"),
            state=d.get("state"),
            last_heartbeat=_parse_dt(d.get("lastheartbeat")),
            connector_summaries=d.get("connectors") or [],
            raw=d,
        )


@dataclass
class UserInfo:
    """Current user profile."""

    id: str
    username: str | int | None
    email: str | None
    language: str | None
    oauth_id: str | None
    first_name: str | None
    last_name: str | None
    relation_id: int | None
    raw: dict[str, Any] = field(repr=False, default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> UserInfo:
        rc = d.get("RelationContact") or {}
        return cls(
            id=str(d.get("Id") or ""),
            username=d.get("Username"),
            email=d.get("EmailAddress") or rc.get("Email"),
            language=d.get("Language"),
            oauth_id=d.get("OAuthId"),
            first_name=rc.get("FirstName"),
            last_name=rc.get("LastName"),
            relation_id=_as_int(rc.get("RelationId")),
            raw=d,
        )
