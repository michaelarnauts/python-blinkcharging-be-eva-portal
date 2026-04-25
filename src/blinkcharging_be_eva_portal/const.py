"""Endpoint constants for the Blink Charging / Blue Corner portal."""

from __future__ import annotations

OAUTH_BASE = "https://oauth.bluecorner.be"
AUTHORIZE_ENDPOINT = f"{OAUTH_BASE}/connect/authorize"
TOKEN_ENDPOINT = f"{OAUTH_BASE}/connect/token"
USERINFO_ENDPOINT = f"{OAUTH_BASE}/connect/userinfo"
ACCOUNT_LOGIN_ENDPOINT = f"{OAUTH_BASE}/Account/Login"

API_BASE = "https://api.bluecorner.be/blue/api/v3.1"

OAUTH_CLIENT_ID = "BCCP"
OAUTH_REDIRECT_URI = "https://eva.blinkcharging.be/oidc-callback"
OAUTH_SCOPE = "openid email profile role Api Cache offline_access"

DEFAULT_TIMEOUT = 30.0
TOKEN_REFRESH_LEEWAY = 60  # seconds before expiry to refresh
