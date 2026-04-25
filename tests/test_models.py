"""Model parsing tests - fixtures are trimmed real responses."""

from __future__ import annotations

from datetime import datetime

from blinkcharging_be_eva_portal.models import ChargePoint, ChargePointSummary, Session, UserInfo


def test_charge_point_summary_parses():
    d = {
        "id": "47000",
        "type": "ChargePoint",
        "chargeboxidentifier": "EXAMPLE-CHARGER-01",
        "model": "Home Go V1.0",
        "description": "Home charger",
        "state": "Online",
        "lastheartbeat": "2026-04-24 16:38:09",
        "connectors": [{"id": "48000", "state": "OCCUPIED"}],
    }
    s = ChargePointSummary.from_dict(d)
    assert s.id == 47000
    assert s.chargeboxidentifier == "EXAMPLE-CHARGER-01"
    assert isinstance(s.last_heartbeat, datetime)
    assert s.connector_summaries[0]["state"] == "OCCUPIED"


def test_charge_point_with_active_session():
    d = {
        "Id": "47000",
        "PublicIdentifier": "EXAMPLE-CHARGER-01",
        "Vendor": "Ohme",
        "ChargerType": "PQ 100",
        "State": "AVAILABLE",
        "OnlineState": "ONLINE",
        "OnlineStateDateTime": "2026-04-24 16:38:09",
        "Connectors": [
            {
                "Id": "48000",
                "Nr": 1,
                "State": "OCCUPIED",
                "SessionState": "CHARGING",
                "StateDetail": "Charging",
                "Power": 2300,
                "Current": 10,
                "Voltage": 230,
                "NumPhases": 1,
                "LastMeterValue": "3337075",
                "ChargeSessionId": 17000001,
                "Session": {
                    "id": "17000001",
                    "State": "CHARGING",
                    "ConsumptionWh": 7834,
                    "CurrentSpeedW": 2300,
                    "ChargingStart": "2026-04-24 12:41:22",
                },
            }
        ],
    }
    cp = ChargePoint.from_dict(d)
    assert cp.is_online
    assert cp.id == 47000
    assert cp.public_identifier == "EXAMPLE-CHARGER-01"
    assert cp.online_state_datetime is not None
    assert cp.online_state_datetime.utcoffset().total_seconds() == 7200
    assert len(cp.connectors) == 1
    conn = cp.connectors[0]
    assert conn.is_plugged
    assert conn.is_charging
    assert conn.last_meter_value_wh == 3337075
    assert conn.active_session is not None
    assert conn.active_session.consumption_wh == 7834
    assert conn.active_session.current_speed_w == 2300
    assert cp.active_session is conn.active_session


def test_session_is_active_flag():
    finished = Session.from_dict({"Id": "1", "State": "FINISHED"})
    assert not finished.is_active
    charging = Session.from_dict({"Id": "2", "State": "CHARGING"})
    assert charging.is_active


def test_user_info_flattens_relation_contact():
    d = {
        "Id": "BCO||10001",
        "Username": 10001,
        "EmailAddress": "me@x",
        "Language": "NL",
        "OAuthId": "uuid",
        "RelationContact": {
            "FirstName": "Alex",
            "LastName": "Example",
            "RelationId": 4300,
            "Email": "me@x",
        },
    }
    u = UserInfo.from_dict(d)
    assert u.first_name == "Alex"
    assert u.last_name == "Example"
    assert u.relation_id == 4300
