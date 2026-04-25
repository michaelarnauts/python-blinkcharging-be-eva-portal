"""High-level async client for the Blink Charging / Blue Corner portal.

Usage::

    async with BlinkChargingClient(username, password) as client:
        user = await client.async_get_user_info()
        chargers = await client.async_get_charge_points()
        for cp in chargers:
            details = await client.async_get_charge_point(cp.id)
            print(details)
"""

from __future__ import annotations

import logging
from types import TracebackType
from typing import Any, Self

import httpx

from .auth import AuthManager, Token
from .const import API_BASE, DEFAULT_TIMEOUT
from .exceptions import BlinkChargingAPIError, BlinkChargingAuthError
from .models import ChargePoint, ChargePointSummary, Session, UserInfo

_LOGGER = logging.getLogger(__name__)


class BlinkChargingClient:
    """Async client that handles auth + API access.

    Can be used as an async context manager (which owns the ``httpx.AsyncClient``),
    or constructed with an externally managed client — useful for Home Assistant
    where integrations are expected to share a single ``aiohttp``/``httpx`` session.
    """

    def __init__(
        self,
        username: str,
        password: str,
        *,
        http: httpx.AsyncClient | None = None,
        token: Token | None = None,
    ) -> None:
        self._username = username
        self._password = password
        self._http = http
        self._owns_http = http is None
        self._auth: AuthManager | None = None
        self._initial_token = token

    async def __aenter__(self) -> Self:
        if self._http is None:
            self._http = httpx.AsyncClient(
                timeout=DEFAULT_TIMEOUT,
                # The Vue SPA sends a generic UA; match something reasonable
                headers={"User-Agent": "blinkcharging-python/0.1"},
            )
        self._auth = AuthManager(
            self._username, self._password, self._http, token=self._initial_token
        )
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.async_close()

    async def async_close(self) -> None:
        if self._owns_http and self._http is not None:
            await self._http.aclose()
            self._http = None

    # ------------------------------------------------------------------ auth

    @property
    def token(self) -> Token | None:
        """Expose the current token so callers (e.g. HA config flow) can persist it."""
        return self._auth.token if self._auth else None

    async def async_login(self) -> None:
        """Force authentication now (instead of lazily on first call)."""
        if not self._auth:
            raise RuntimeError("Client not entered; use 'async with' first")
        await self._auth.async_get_access_token()

    # --------------------------------------------------------------- API calls

    async def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        if not self._auth or not self._http:
            raise RuntimeError("Client not entered; use 'async with' first")
        token = await self._auth.async_get_access_token()
        headers = kwargs.pop("headers", {}) or {}
        headers["Authorization"] = f"Bearer {token}"
        headers.setdefault("Accept", "application/json")
        url = f"{API_BASE}{path}"

        resp = await self._http.request(method, url, headers=headers, **kwargs)
        if resp.status_code == 401:
            # Token might have been revoked server-side; retry once after re-auth.
            await self._auth.async_invalidate()
            token = await self._auth.async_get_access_token()
            headers["Authorization"] = f"Bearer {token}"
            resp = await self._http.request(method, url, headers=headers, **kwargs)

        if resp.status_code == 401:
            raise BlinkChargingAuthError("Not authorized (after retry)")
        if resp.status_code == 403:
            raise BlinkChargingAPIError(f"Forbidden: {path}", status_code=403)
        if resp.status_code >= 400:
            raise BlinkChargingAPIError(
                f"HTTP {resp.status_code} on {path}: {resp.text[:200]}",
                status_code=resp.status_code,
            )

        try:
            payload = resp.json()
        except ValueError as err:
            raise BlinkChargingAPIError(
                f"Non-JSON response from {path}: {resp.text[:200]}"
            ) from err

        # The portal wraps responses in {"result": {"status": "success"|"error", ...}, "data": ...}
        result = payload.get("result") if isinstance(payload, dict) else None
        if isinstance(result, dict) and result.get("status") == "error":
            raise BlinkChargingAPIError(
                result.get("message") or f"API error on {path}",
                errorcode=result.get("errorcode"),
            )
        if isinstance(payload, dict) and "data" in payload:
            return payload["data"]
        return payload

    # ----- user -----

    async def async_get_user_info(self) -> UserInfo:
        data = await self._request("GET", "/user/BCO/UserInfo")
        return UserInfo.from_dict(data)

    # ----- chargers -----

    async def async_get_charge_points(self) -> list[ChargePointSummary]:
        data = await self._request("GET", "/chargepoint/BCO/list")
        if not isinstance(data, list):
            return []
        return [ChargePointSummary.from_dict(d) for d in data if isinstance(d, dict)]

    async def async_get_charge_point(self, charge_point_id: int | str) -> ChargePoint:
        """Get full charger detail, including connectors and any active session."""
        data = await self._request("GET", f"/chargepoint/BCO/{charge_point_id}")
        return ChargePoint.from_dict(data)

    async def async_get_charge_point_minimal(self, charge_point_id: int | str) -> ChargePoint:
        """Cheaper variant that still returns connectors + live session.

        This is the one to call from a Home Assistant ``DataUpdateCoordinator``
        on each refresh — the `/chargepoint/BCO/{id}` variant returns more
        config-style metadata the HA integration doesn't need every tick.
        """
        data = await self._request("GET", f"/chargepoint/BCO/Minimal/{charge_point_id}")
        # The Minimal response is the charger dict with Connectors + Placements,
        # but without the top-level Id etc. We inject the id back so models match.
        if isinstance(data, dict):
            data.setdefault("Id", str(charge_point_id))
        return ChargePoint.from_dict(data)

    # ----- sessions -----

    async def async_get_session(self, session_id: int | str) -> Session:
        data = await self._request("GET", f"/session/BCO/details/{session_id}")
        return Session.from_dict(data)

    async def async_get_recent_sessions(self, charge_point_id: int | str) -> list[Session]:
        """Last ~10 sessions for a charge point, newest first."""
        data = await self._request("GET", f"/session/BCO/lasttenbycp/{charge_point_id}")
        if not isinstance(data, list):
            return []
        return [Session.from_dict(d) for d in data if isinstance(d, dict)]

    async def async_get_sessions_filtered(
        self,
        *,
        skip: int = 0,
        take: int = 25,
        extra_params: dict[str, Any] | None = None,
    ) -> list[Session]:
        """Filtered session list endpoint used by the portal's 'Sessions' page.

        The full parameter set is not yet reverse-engineered; this wraps the
        default ``skip/take`` paging. ``extra_params`` is passed through as query
        string for experimentation.
        """
        params: dict[str, Any] = {"skip": skip, "take": take}
        if extra_params:
            params.update(extra_params)
        data = await self._request("GET", "/session/BCO/sessionlist/filtered", params=params)
        records = (data or {}).get("records") if isinstance(data, dict) else None
        if not isinstance(records, list):
            return []
        return [Session.from_dict(d) for d in records if isinstance(d, dict)]

    # ----- convenience -----

    async def async_get_snapshot(self) -> dict[str, Any]:
        """Fetch everything for a one-shot view of the account.

        Returns::

            {
              "user": UserInfo,
              "charge_points": {id: ChargePoint, ...},  # full detail
            }

        For an HA ``DataUpdateCoordinator`` tick, prefer calling
        :meth:`async_get_charge_point_minimal` directly — the ``Minimal``
        endpoint omits the (static) top-level charger metadata and is
        cheaper per poll.
        """
        user = await self.async_get_user_info()
        summaries = await self.async_get_charge_points()
        chargers: dict[int, ChargePoint] = {}
        for s in summaries:
            try:
                chargers[s.id] = await self.async_get_charge_point(s.id)
            except BlinkChargingAPIError as err:
                _LOGGER.warning("Failed to fetch charger %s: %s", s.id, err)
        return {"user": user, "charge_points": chargers}
