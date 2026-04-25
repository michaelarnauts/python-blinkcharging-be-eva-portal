"""OAuth / OIDC auth for the Blink Charging / Blue Corner portal.

The portal uses IdentityServer4 with PKCE + authorization_code. The public
SPA client ``BCCP`` does NOT permit the ``password`` grant, so we simulate
the interactive flow:

1. GET /connect/authorize (302 → auth.bluecorner.be/login)
2. POST /Account/Login (JSON) with the user's credentials and the
   ``ReturnUrl`` we were redirected with
3. Follow the returned ``redirectUrl`` back through /connect/authorize/callback
   → ?code=... on the SPA's oidc-callback URI
4. POST /connect/token with the code + PKCE verifier

After that we have an access + refresh token and can refresh normally.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import logging
import secrets
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx

from .const import (
    ACCOUNT_LOGIN_ENDPOINT,
    AUTHORIZE_ENDPOINT,
    OAUTH_CLIENT_ID,
    OAUTH_REDIRECT_URI,
    OAUTH_SCOPE,
    TOKEN_ENDPOINT,
    TOKEN_REFRESH_LEEWAY,
)
from .exceptions import BlinkChargingAuthError

_LOGGER = logging.getLogger(__name__)


def _pkce_pair() -> tuple[str, str]:
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode().rstrip("=")
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    )
    return verifier, challenge


@dataclass
class Token:
    """A token set plus its expiry time (monotonic-ish, from epoch)."""

    access_token: str
    refresh_token: str | None
    expires_at: float  # epoch seconds
    token_type: str = "Bearer"
    scope: str | None = None
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_token_response(cls, payload: dict[str, Any]) -> Token:
        expires_in = int(payload.get("expires_in") or 3600)
        return cls(
            access_token=payload["access_token"],
            refresh_token=payload.get("refresh_token"),
            expires_at=time.time() + expires_in,
            token_type=payload.get("token_type", "Bearer"),
            scope=payload.get("scope"),
            raw=payload,
        )

    @property
    def is_expired(self) -> bool:
        return time.time() >= (self.expires_at - TOKEN_REFRESH_LEEWAY)


class AuthManager:
    """Owns the login flow, the current token, and refresh.

    Intended to be held for the lifetime of a client. Thread/coroutine-safe
    refresh via an ``asyncio.Lock``.
    """

    def __init__(
        self,
        username: str,
        password: str,
        http: httpx.AsyncClient,
        *,
        token: Token | None = None,
    ) -> None:
        self._username = username
        self._password = password
        self._http = http
        self._token = token
        self._lock = asyncio.Lock()

    @property
    def token(self) -> Token | None:
        return self._token

    async def async_get_access_token(self) -> str:
        """Return a valid access token, refreshing or re-logging-in as needed."""
        async with self._lock:
            if self._token is None:
                await self._interactive_login()
            elif self._token.is_expired:
                try:
                    await self._refresh()
                except BlinkChargingAuthError:
                    _LOGGER.info("Refresh failed; falling back to full login")
                    await self._interactive_login()
        assert self._token is not None
        return self._token.access_token

    async def async_invalidate(self) -> None:
        """Force a full re-auth on next ``async_get_access_token``."""
        async with self._lock:
            self._token = None

    async def _interactive_login(self) -> None:
        """Run the full PKCE + form-login flow and store the resulting token.

        Handles both fresh sessions (→ login page → POST creds) and the
        case where the shared HTTP client already has a valid
        IdentityServer4 session cookie (→ authorize endpoint issues a
        code immediately without prompting).
        """
        verifier, challenge = _pkce_pair()
        state = secrets.token_urlsafe(16)
        nonce = secrets.token_urlsafe(16)

        auth_params = {
            "client_id": OAUTH_CLIENT_ID,
            "redirect_uri": OAUTH_REDIRECT_URI,
            "response_type": "code",
            "scope": OAUTH_SCOPE,
            "state": state,
            "nonce": nonce,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }

        # 1. authorize. Two possible endings:
        #    (a) auth.bluecorner.be/login?ReturnUrl=…   — user must log in
        #    (b) eva.blinkcharging.be/oidc-callback?code=… — existing session, code ready
        final = await self._follow_redirects(
            await self._http.get(AUTHORIZE_ENDPOINT, params=auth_params, follow_redirects=False)
        )
        final_url = str(final.url)

        if final_url.startswith(OAUTH_REDIRECT_URI):
            # (b) Short-circuit: server had a valid session, code is in final.url.
            code = parse_qs(urlparse(final_url).query).get("code", [None])[0]
            if not code:
                raise BlinkChargingAuthError(
                    f"Authorize returned callback URL without a code: {final_url}"
                )
            await self._exchange_code(code, verifier)
            return

        # (a) Normal path: landed on the login page with ?ReturnUrl=…
        return_url_q = parse_qs(urlparse(final_url).query).get("ReturnUrl")
        if not return_url_q:
            raise BlinkChargingAuthError(f"Unexpected authorize redirect target: {final_url}")
        return_url = return_url_q[0]

        # 2. POST credentials
        login_body = {
            "username": self._username,
            "password": self._password,
            "rememberLogin": True,
            "altUsername": "",
            "returnUrl": return_url,
        }
        resp = await self._http.post(ACCOUNT_LOGIN_ENDPOINT, json=login_body)
        if resp.status_code != 200:
            raise BlinkChargingAuthError(
                f"Login POST failed: HTTP {resp.status_code}: {resp.text[:200]}"
            )
        try:
            data = resp.json()
        except ValueError as err:
            raise BlinkChargingAuthError("Login response was not JSON") from err
        if not data.get("isOk") and not data.get("redirectUrl"):
            err = (data.get("error") or {}).get("error") or data.get("error") or "unknown"
            raise BlinkChargingAuthError(f"Login rejected: {err}")
        redirect_url = data.get("redirectUrl")
        if not redirect_url:
            raise BlinkChargingAuthError(f"Login returned no redirectUrl: {data}")

        # 3. Follow redirect to pick up the auth code
        code = await self._extract_code_from_redirect_chain(redirect_url)
        if not code:
            raise BlinkChargingAuthError(
                "Did not receive an authorization code after login redirects"
            )

        # 4. Exchange code for token
        await self._exchange_code(code, verifier)

    async def _extract_code_from_redirect_chain(self, start_url: str) -> str | None:
        """Walk 3xx redirects from ``start_url`` and return the ``code`` parameter
        as soon as we see a Location pointing at :data:`OAUTH_REDIRECT_URI`."""
        r = await self._http.get(start_url, follow_redirects=False)
        visited = 0
        while r.is_redirect and visited < 10:
            loc = r.headers["location"]
            if loc.startswith(OAUTH_REDIRECT_URI):
                return parse_qs(urlparse(loc).query).get("code", [None])[0]
            if loc.startswith("/"):
                loc = str(r.url.join(loc))
            r = await self._http.get(loc, follow_redirects=False)
            visited += 1
        # Final non-redirect response might itself be at the callback URI.
        if str(r.url).startswith(OAUTH_REDIRECT_URI):
            return parse_qs(urlparse(str(r.url)).query).get("code", [None])[0]
        return None

    async def _exchange_code(self, code: str, verifier: str) -> None:
        """Swap an authorization code + PKCE verifier for an access/refresh token."""
        tok_resp = await self._http.post(
            TOKEN_ENDPOINT,
            data={
                "grant_type": "authorization_code",
                "client_id": OAUTH_CLIENT_ID,
                "code": code,
                "redirect_uri": OAUTH_REDIRECT_URI,
                "code_verifier": verifier,
            },
        )
        if tok_resp.status_code != 200:
            raise BlinkChargingAuthError(
                f"Token exchange failed: HTTP {tok_resp.status_code}: {tok_resp.text[:200]}"
            )
        self._token = Token.from_token_response(tok_resp.json())
        _LOGGER.debug("Login OK, token expires at %s", self._token.expires_at)

    async def _refresh(self) -> None:
        assert self._token is not None
        if not self._token.refresh_token:
            raise BlinkChargingAuthError("No refresh token available")
        r = await self._http.post(
            TOKEN_ENDPOINT,
            data={
                "grant_type": "refresh_token",
                "client_id": OAUTH_CLIENT_ID,
                "refresh_token": self._token.refresh_token,
            },
        )
        if r.status_code != 200:
            raise BlinkChargingAuthError(f"Refresh failed: HTTP {r.status_code}: {r.text[:200]}")
        self._token = Token.from_token_response(r.json())
        _LOGGER.debug("Token refresh OK")

    async def _follow_redirects(self, resp: httpx.Response, *, limit: int = 10) -> httpx.Response:
        """Follow 3xx redirects manually so we can inspect intermediate URLs."""
        visited = 0
        while resp.is_redirect and visited < limit:
            loc = resp.headers["location"]
            if loc.startswith("/"):
                loc = str(resp.url.join(loc))
            resp = await self._http.get(loc, follow_redirects=False)
            visited += 1
        return resp
