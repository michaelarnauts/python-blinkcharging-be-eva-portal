# Blink Charging / Blue Corner API — Reference

Unofficial notes from reverse-engineering the Vue SPA at
[eva.blinkcharging.be](https://eva.blinkcharging.be) (the Belgian Blink
Charging customer portal, formerly Blue Corner). Use this doc as a map
when adding new client methods.

> All of this is subject to change without notice. Nothing here is
> officially documented by Blink / Blue Corner.

---

## Hosts

| Purpose | Host |
| ------- | ---- |
| SPA frontend | `eva.blinkcharging.be` (also serves at `eva.bluecorner.be`) |
| OAuth / OIDC (IdentityServer4) | `oauth.bluecorner.be` |
| Login UI SPA | `auth.bluecorner.be` |
| Main REST API | `api.bluecorner.be` |
| Public maps / roaming | `api.bluecorner.be/blue/api/locations/1.2/BCO/maplist/public` |
| Feature flags | `api.flagsmith.com/api/v1/flags/` |

The API uses the legacy `BCO` ("Blue Corner Operator") tenant prefix
throughout — even after the Blink rebrand.

---

## Authentication

IdentityServer4 OIDC. Discovery:

```
GET https://oauth.bluecorner.be/.well-known/openid-configuration
```

Useful fields from discovery:

- `authorization_endpoint`: `/connect/authorize`
- `token_endpoint`: `/connect/token`
- `userinfo_endpoint`: `/connect/userinfo`
- `end_session_endpoint`: `/connect/endsession`
- `revocation_endpoint`: `/connect/revocation`
- `scopes_supported`: `role`, `Api`, `phone`, `profile`, `address`, `email`, `openid`, `Cache`, `offline_access`
- `grant_types_supported`: `authorization_code`, `client_credentials`, `refresh_token`, `implicit`, `password`, `device_code`
- `id_token_signing_alg_values_supported`: `RS256`
- JWKS: `https://oauth.bluecorner.be/.well-known/openid-configuration/jwks`

### Client registration (SPA)

From the Vue SPA bundle:

| Setting | Value |
| ------- | ----- |
| `client_id` | `BCCP` |
| `redirect_uri` | `https://eva.blinkcharging.be/oidc-callback` |
| `response_type` | `code` |
| `scope` | `openid email profile role Api Cache offline_access` |
| PKCE | Required (`code_challenge_method=S256`) |

The `BCCP` client is public (no secret) and does **not** permit the
`password` grant, even though the issuer advertises it — a direct
`grant_type=password` POST returns `unauthorized_client`.

### Headless login flow

The library simulates the SPA flow end-to-end:

1. **GET `/connect/authorize`** with PKCE `code_challenge`. Returns a
   302 chain ending at `https://auth.bluecorner.be/login?ReturnUrl=...`
   (where `ReturnUrl` is the `oauth.bluecorner.be/connect/authorize/callback?...`
   URL with all original params).
2. **POST `https://oauth.bluecorner.be/Account/Login`** as JSON:
   ```json
   {
     "username": "you@example.com",
     "password": "…",
     "rememberLogin": true,
     "altUsername": "",
     "returnUrl": "<the ReturnUrl from step 1>"
   }
   ```
   Response on success:
   ```json
   {
     "redirectUrl": "https://oauth.bluecorner.be/connect/authorize/callback?...",
     "isOk": true,
     "context": { … },
     "info": { … }
   }
   ```
   On failure, `isOk` is `false` and `error.error` gives a short code
   (e.g. `LOCKEDOUT`). The SPA uses `login.<error.error>` as an i18n key.
3. **GET `redirectUrl`** (no `follow_redirects`). The server now has a
   session cookie and issues a 302 to
   `https://eva.blinkcharging.be/oidc-callback?code=…&state=…&scope=…&session_state=…`.
   Read `code` from the query string.
4. **POST `/connect/token`** form-encoded:
   ```
   grant_type=authorization_code
   client_id=BCCP
   code=<from step 3>
   redirect_uri=https://eva.blinkcharging.be/oidc-callback
   code_verifier=<PKCE verifier>
   ```
   Response:
   ```json
   {
     "id_token": "…",
     "access_token": "…",
     "expires_in": 3600,
     "token_type": "Bearer",
     "refresh_token": "…",
     "scope": "openid email profile role Api Cache offline_access"
   }
   ```

### Refresh

```
POST /connect/token
grant_type=refresh_token
client_id=BCCP
refresh_token=<…>
```

Returns a fresh token set (with a rotated `refresh_token`). If the
refresh token has expired or been revoked, the server returns 400;
the library falls back to a full interactive login in that case.

### Access-token claims (from `/connect/userinfo`)

```json
{
  "name": "Alex Example",
  "given_name": "Alex",
  "family_name": "Example",
  "email": "you@example.com",
  "aud": "Api",
  "role": "User",
  "language": "EN",
  "sub": "<oauth-id UUID>"
}
```

---

## API base & response envelope

```
https://api.bluecorner.be/blue/api/v3.1
```

The SPA also uses `v3` in some places. `v3.1` works for everything we
need. Requests require `Authorization: Bearer <access_token>`.

Every endpoint wraps its payload:

```json
{
  "result": { "status": "success" },
  "data": { … }         // or [ … ] for list endpoints
}
```

On error:

```json
{
  "result": {
    "status": "error",
    "errorcode": "Unauthorized",
    "message": "You do not have access to this resource.",
    "errorid": ""
  }
}
```

HTTP-level codes:

- `200` — normal success (even for "soft" errors — always check `result.status`)
- `401` — missing/expired token; re-auth and retry
- `403` — `result.errorcode: Unauthorized` — the user lacks the role for
  that endpoint (e.g. `/chargepoint/BCO/Stats` for a regular user)
- `404` — wrong path or unknown ID
- `405` — endpoint exists but GET not allowed (expects POST/PUT)

### Date/time formats

Two formats appear, sometimes in the same response:

- `"2026-04-24 16:38:09"` — naive, server-local (the library currently treats these as `Europe/Brussels`)
- `"2026-04-21T09:28:28+02:00"` — ISO-8601 with offset (mostly from `/session/BCO/sessionlist/filtered`)

Empty strings `""` are commonly used instead of `null`.

### Units

- Energy: **Wh** (e.g. `ConsumptionWh`, `LastMeterValue` — the latter is
  a cumulative counter suitable for HA's Energy Dashboard)
- Power: **W** (e.g. `CurrentSpeedW`, `MaxSpeedW`, connector `Power`)
- Current: **A** (connector `Current` — this is the configured limit, not live draw)
- Voltage: **V** (connector `Voltage` — nominal, not measured)

---

## Endpoints

Confirmed (✅), listed but untested (❓), admin-only for this user (🔒),
server-side broken (⚠️), unauthenticated public (📖).

### User

#### ✅ `GET /user/BCO/UserInfo`

Returns the authenticated user's profile + `RelationContact` (name,
address, relationId). Primary key is `Id` like `BCO||10001`; the
numeric `Username` (`10001`) is their internal user number.

```json
{
  "Id": "BCO||10001",
  "OAuthId": "00000000-0000-0000-0000-000000000001",
  "EmailAddress": "…",
  "Language": "NL",
  "Username": 10001,
  "RelationContact": {
    "FirstName": "…",
    "LastName": "…",
    "RelationId": 4300,
    "Email": "…",
    "City": "…",
    "Country": "BE",
    "HouseNumber": "…",
    "PostalCode": "…",
    "RelationDescriptionList": "Fleet Partner;Example Corp;…",
    "RelationIdList": "4100;4200;4300"
  }
}
```

Note the multiple relations: the user can belong to several organizations
(employer, leasing company, personal). `RelationId` is the currently-selected
one; the others live in `RelationIdList`.

#### ❓ `GET /user/BCO/Setup` → 405 (expects POST, body unknown)

Referenced in the SPA but not yet mapped.

#### 🔒 `POST /user/BCO/CreateUser`, `PUT /user/BCO/ActivateUser/{id}`, `PUT /user/BCO/DeactivateUser/{id}`
#### 🔒 `POST /user/BCO/assign/manager/{id}`, `DELETE /user/BCO/remove/manager/{id}`
#### 🔒 `POST /user/BCO/contact/intorelation/{id}`

Admin / fleet-manager endpoints; out of scope for a regular user.

#### ❓ `PUT https://oauth.bluecorner.be/api/User/ChangePassword`

Different host (on `oauth.bluecorner.be`, not the API). Takes a body with
old/new password. Would be needed for a future "change password" feature.

---

### Charge points

#### ✅ `GET /chargepoint/BCO/list`

Lightweight list of every charger the user can see. One entry per charger:

```json
{
  "id": "47000",
  "type": "ChargePoint",
  "haschildren": false,
  "ownerdescr": "Example Corp",
  "chargeboxidentifier": "EXAMPLE-CHARGER-01",
  "model": "Home Go V1.0",
  "chargepointserialnumber": "EXAMPLE-CHARGER-01",
  "onlinestatedatetime": "2026-04-24 16:38:09",
  "description": "Fleet Partner - Smart Cable - Example Corp - …",
  "state": "Online",
  "lastheartbeat": "2026-04-24 16:38:09",
  "connectors": [
    {
      "id": "48000",
      "state": "OCCUPIED",
      "sessionid": 17000001,
      "sessionstate": "PARKING"
    }
  ],
  "placements": [
    {
      "locationlabel": "…",
      "locationlat": "50.867064",
      "locationlng": "4.733284",
      "address": "…",
      "street": "…", "housenr": "…", "postalcode": "…", "city": "…", "country": "BE",
      "evtype": "PRIVATE",
      "published": "NO",
      "reimbursement": "52523",
      "hasreimbursement": true,
      "contract": { "id": "52523", "contractType": "3", "children": [ … ] }
    }
  ]
}
```

Good for discovery; doesn't include live power/energy. Use the per-charger
endpoints below for that.

#### ✅ `GET /chargepoint/BCO/{id}`

Full charger detail. Includes everything from the list plus:

- Top-level: `AdminState`, `BootNotificationDateTime`, `ChargerType`,
  `OnlineState`, `Vendor`, `PublicIdentifier`, `TechClassification`,
  `TechType`, `OwnerId`, `CpoId`, `CurrentError`, `LastError`
- `Connectors[*]`:
  - Identity: `Id`, `Nr`, `ChargePointId`, `Uci`
  - Electrical: `Current` (A — configured), `Voltage` (V), `NumPhases`, `Power` (W — max)
  - State: `State` (`AVAILABLE`, `OCCUPIED`, `OFFLINE`, `ERROR`…),
    `SessionState` (`PARKING`, `CHARGING`, `FINISHED`, …),
    `StateDetail` (OCPP-like: `SuspendedEV`, `Charging`, `Finishing`…),
    `StateDateTime`, `AdminState`, `ErrorState`
  - Metering: `LastMeterValue` (Wh, cumulative), `LastMeterValueId`,
    `MeterSerial`, `MonopolizeChargePoint`
  - Session link: `ChargeSessionId`, `ChargingMode` (`AC`/`DC`), `Session` (embedded full session — see below)
  - Errors: `LastError` (e.g. `OtherError`), `LastErrorDateTime`,
    `CurrentDownTimeId`

#### ✅ `GET /chargepoint/BCO/Minimal/{id}`

Same `Connectors[*]` as the full endpoint (including embedded `Session`),
plus a `Placements` array, but without the top-level charger metadata.
**This is the endpoint to poll from a Home Assistant
`DataUpdateCoordinator`** — it has the live session data with a smaller
payload than the full endpoint.

Quirk: the response doesn't echo back the charger `Id`; the library
injects it client-side from the request path.

#### ✅ `GET /chargepoint/BCO/{id}/Settings`

Per-placement feature flags, for both the currently-active placement
(`CurrentPlacements[]`) and any future-dated ones (`FuturePlacements[]`).

```json
{
  "CurrentPlacements": [
    {
      "PlugAndCharge": {
        "IsEnabled": 0, "IsReimbursed": 1,
        "ReimburseeId": "4300", "ReimburserId": "4100",
        "SubscriptionTypeId": "SUB_PARTNER_CREG",
        "CustomFee": "SUB_PARTNER_CREG"
      },
      "GuestCharging": {
        "IsEnabled": 0, "IsPublished": 0, "IsReimbursed": 0,
        "SubscriptionTypeId": "", "CustomFee": "", "ReimburseeId": ""
      },
      "WhiteListing": {
        "IsEnabled": 0, "IsReimbursed": "",
        "SubscriptionTypeId": "", "CustomFee": ""
      },
      "PlacementId": "370000",
      "ConnectorNr": 1,
      "Start": "2024-03-31 00:00:00",
      "End": ""
    }
  ],
  "FuturePlacements": [ … ],
  "Type": 2
}
```

Good candidate for future HA `switch.*_plug_and_charge` and
`switch.*_guest_charging` entities — assuming the accompanying write
endpoints below accept them.

#### 🔒 `GET /chargepoint/BCO/Stats` → 403 for a regular user

CPO/dashboard aggregate stats. Accessible from admin-role accounts that
see the fleet-wide dashboard; regular end-users get `Unauthorized`.

#### ❓ `POST /chargepoint/BCO/Update`

Presumably updates charger configuration. Body unknown.

#### ❓ `POST /update/guestcharging`, `POST /update/isplugandcharge`

Per-charger feature toggles seen in the SPA settings page. Body unknown —
probably `{ chargePointId, enabled }` or similar. Presumed writes for the
flags returned by `/chargepoint/BCO/{id}/Settings`.

---

### Charge placements / locations

#### ❓ `GET /chargeplacement/BCO/{id}` → 404 for a ChargePoint id

Needs a placement id, not a charger id. The charger detail response has
`ChargePointPlacementId` and `PlacementEvseId` (e.g. `BE*BCA*E129561*001`).

#### ✅ `GET /chargeplacement/BCO/{charge_point_id}/contractdetails`

**Note:** despite the name, this takes the **charge-point id**, not the
placement id. Small summary of the placement's contract category:

```json
{
  "evtype": "DEMO",
  "isplugandcharge": 0,
  "isreimbtowhitelist": 0,
  "published": 0
}
```

`evtype` values seen: `PRIVATE`, `SEMI_PUBLIC`, `PUBLIC`, `DEMO`.

#### ✅ `GET /chargeplacement/BCO/{charge_point_id}/whitelistgroup`

Whitelist/access-group membership for the placement. For a home user
with no whitelist set up, returns:

```json
{ "WhiteListGroup": {} }
```

Expected to contain an array of RFID token ids / groups when configured.

#### ❓ `GET /chargelocation/BCO/list`
#### ❓ `POST /chargelocation/BCO/createupdate`

Physical location CRUD.

#### 📖 `GET /locations/1.2/BCO/maplist/public?countries=["BE"]&roaming=0`

**Unauthenticated** endpoint used by the public map. Returns every
publicly-listed charger in Belgium. Useful for roaming apps, not for
the user's own charger.

---

### Sessions

#### ✅ `GET /session/BCO/details/{session_id}`

Full session record. Top-level fields you probably want:

- `Id`, `ChargePointId`, `ChargePointName`, `ChargePointPlacementId`
- `EVSEId`, `EVSENumber`, `PlacementEvseId` (e.g. `BE*BCA*E129561*001`)
- `ChargeLocation*` — duplicate of the placement address
- Timing: `CreatedOn`, `SessionStart`, `SessionEnd`, `ChargingStart`,
  `ChargingEnd`, `LastSignOfLife`, `StateDateTime`
- State: `State` (`PARKING`, `CHARGING`, `FINISHED`…), `StateReason`,
  `StartReason`, `StopReason` (e.g. `STOPTRANSACTION`, `OLDCPMSEVENT`)
- Energy/power: `ConsumptionWh`, `CurrentSpeedW` (live power!),
  `MaxSpeedW`, `MeterStart` (Wh), `MeterEnd` (Wh — empty while active),
  `MeterValueStartId`, `MeterValueEndId`, `LastMeterValueId`
- Identifiers: `Pin` (the 4-digit PIN shown on the portal),
  `ParkingSpotId`, `ParkingSpotLabel`, `FinancialTransactionId`,
  `InvoiceFlowTrackerId`
- CPO/MSP: `CpoId`, `CpoDescr`, `CpoIssuer`, `MspId`, `MspDescr`, `MspIssuer`
- Tariff/subscription: `CustSubscriptionId`, `CustSubscriptionDescr`,
  `CustTariffId`, `CustTariffPlacementCategory`, `CustTariffSubscriptionCategory`
- Linkage: `PrevSession`, `NextSession`,
  `PreviousSessionFromChargePointPlacement`, `PreviousSessionFromLocation`,
  `PreviousSessionFromToken`

Notes:

- `SessionStart` / `SessionEnd` bracket the whole plug-in/plug-out cycle.
- `ChargingStart` / `ChargingEnd` bracket only the time the car was
  actually drawing power. While a car is parked but fully charged
  (`SuspendedEV`), `State` stays `PARKING` and `ChargingEnd` is set.
- `CurrentSpeedW` drops to a small residual (30-50 W) when the car
  stops drawing power — treat values below ~100 W as idle.

#### ✅ `GET /session/BCO/lasttenbycp/{charge_point_id}`

Most recent ~10 sessions for one charger, newest first. Same record
shape as `/details/{id}`.

#### ✅ `GET /session/BCO/sessionlist/filtered?skip=&take=&…`

Paged session list used by the portal's "Sessions" page.

Response:

```json
{
  "data": {
    "records": [ … ],
    "totalCount": …
  }
}
```

Records here are slimmer than `/details/{id}` and use the ISO-8601 date
format with offsets:

```json
{
  "ChargePoint": { "ChargeLocationStreet": "…", "…": "…" },
  "User": { "PrintedNumber": "NA" },
  "ChargeSession": {
    "Start": "2026-04-21T09:28:28+02:00",
    "End":   "2026-04-23T08:43:38+02:00"
  },
  "Consumption": 6007,
  "Rotation": "",
  "State": "FINISHED",
  "SessionId": 17000002,
  "chargepointlabel": "EXAMPLE-CHARGER-01",
  "CustomerReference": ""
}
```

The full filter vocabulary is not yet reverse-engineered; known params
are `skip`, `take`. Expect date-range, chargepoint, state filters too —
check the SPA's "Sessions" page network traffic when needed.

---

### Relations (organizations)

Relations are the org/customer entities the portal is built around. Users
can belong to multiple relations (e.g. a Fleet Partner leasing account → an
Example Corp company account → a personal leaf). The leaf relation is the
one whose chargers/sessions the dashboard currently shows.

#### ✅ `GET /relation/BCO/{id}`

Full relation record — banking, VAT, parent, and a pre-computed
breadcrumb up to the root:

```json
{
  "Id": "4300",
  "Name": "Alex Example",
  "Description": "Alex Example",
  "IsCompany": 0,
  "ParentId": 4200,
  "Email": "…", "Phone": "+32…",
  "Street": "Examplelaan", "HouseNumber": "10", "PostalCode": "1000", "City": "Brussels", "Country": "BE",
  "BankAccountIban": "…", "BankAccountBic": "…",
  "VatNr": "", "Reference": "REF-000123", "AccountancyId": "…",
  "PartnerType": "706446",
  "MainContactId": 5300,
  "RelationIdList": "4100;4200",
  "RelationDescriptionList": "Fleet Partner;Example Corp",
  "Breadcrumb": [
    { "Id": "4100", "Description": "Fleet Partner", "Key": 1 },
    { "Id": "4200", "Description": "Example Corp",  "Key": 2 }
  ]
}
```

#### ✅ `GET /relation/BCO/treeview/-1/Relation`

Discovers your relation tree, rooted at the leaf and walking up. For a
leaf user returns:

```json
{
  "parent": {
    "id": "4300", "key": 123456789, "type": "Relation",
    "haschildren": 0, "description": "Alex Example",
    "icon": 2, "iscompany": 0
  },
  "relations": [],
  "relationcontacts": []
}
```

For a parent (company/fleet) relation, `relations[]` and
`relationcontacts[]` list its children.

#### ✅ `GET /relation/BCO/treeviewer`

Similar shape to `treeview`, omits `relationcontacts`. The SPA uses this
for a compact org selector.

#### ✅ `GET /relationcontact/BCO/list`

List of human contacts (employees, drivers) attached to the current
relation, each with flags like `isentitymanager`, `hasportal`:

```json
[
  {
    "id": 5300,
    "description": "Alex Example",
    "relationid": 4300,
    "relationdesc": "Alex Example",
    "firstname": "Alex", "lastname": "Example",
    "telephone": "+32…", "email": "…",
    "isentitymanager": false,
    "address": { "street": "Examplelaan", "housenumber": "10", "city": "Brussels", "postalcode": "1000", "country": "BE" },
    "hasportal": false, "isactive": true
  }
]
```

#### ⚠️ `GET /relation/BCO/{id}/subscriptiontype/list/filtered`

Returns an `Error18` ("`<DIVIDE>`") server error when called without
paging params — the controller appears to divide by zero when `take`/`skip`
are missing. Retry with `?skip=0&take=25` before using. Presumably lists
tariff/subscription templates available to the relation.

---

### Tokens (RFID cards)

#### ✅ `GET /token/BCO/list`

List of RFID/charge cards linked to the current relation. Empty array
for users without a card.

#### ✅ `GET /token/BCO/Stats`

```json
{ "mytokens": 0, "subtokens": 0 }
```

`mytokens` = cards directly on the user's relation; `subtokens` = cards
on child relations (for fleet managers).

#### ❓ `GET /session/BCO/lasttenbytoken/{token_id}`

Recent sessions for one RFID card. Needs a token id from
`/token/BCO/list`.

---

### Indicators (dashboard KPIs)

#### ✅ `GET /indicator/BCO/KWHMyChargers`

Monthly energy delivered by the user's own chargers, broken out by
month and charge point. Great source for a Home Assistant monthly
statistics sensor.

```json
[
  {
    "identifier": "2025||10",
    "year": 2025, "label": 10,
    "count": 29,                // # sessions this month
    "value": 138276,            // Wh delivered
    "totaltime": 1735244,       // seconds plugged-in (not necessarily charging)
    "details": [
      { "chargepointid": 37803, "count": 29, "total": 138276, "totaltime": 1735244 }
    ]
  },
  …
]
```

- Units: `value` / `total` are **Wh**, `totaltime` is **seconds**.
- `identifier` is `"YYYY||MM"` (note the double pipe) and `label` is the
  month number (1-12).
- `details[]` breaks the monthly total down per-charger, useful when the
  user has multiple chargers.
- The array is NOT sorted by date; sort client-side on `year` + `label`.

#### ✅ `GET /indicator/BCO/KWHMyTokens`

Same shape as `KWHMyChargers` but for energy consumed via the user's
RFID cards (at any charger). Returns `{}` when the user has no tokens.

---

### UI

#### ✅ `GET /banner/BCO/Banner`

Active site-wide banner (e.g. planned-maintenance notice). Returns an
empty string `""` when none is active; otherwise a short HTML/text
message. Probably safe to surface as a diagnostic attribute if
non-empty.

---

### Tickets / support

#### ❓ `POST /jira/BCO/issue/chargepoint`

Opens a Jira ticket against a charge point. Used by the SPA's "Report
an issue" flow.

#### ❓ `GET /jira/BCO/attachment/download/{id}`
#### ❓ `POST /attachment`, `POST /comment`, `GET /media/{id}`

File and comment endpoints for the Jira ticket flow.

---

### Feature flags

#### 📖 `GET https://api.flagsmith.com/api/v1/flags/`

Flagsmith — not a Blink endpoint. The SPA uses it to gate UI features
(charge-points page, tokens page, etc.). Keys seen in the bundle
correspond to `Xe["a"]`, `Xe["c"]`, `Xe["d"]` in the minified JS.
Irrelevant for API clients.

---

## Known user roles

`role` claim values observed / referenced in the bundle: `User`,
`CustomerAdmin`, `Manager`, `Admin`, `Support`. Regular end users get
`User`. Endpoints with 🔒 above require higher roles.

## Multi-relation users

Users who belong to multiple organizations (e.g. personal + company car
leasing) have a `RelationIdList` in their profile. The API scopes list
endpoints to the currently-selected relation (the **leaf**); everything
else is reachable by walking upward via `ParentId` / the `Breadcrumb`
array on `/relation/BCO/{id}`.

For the test account:

```
Fleet Partner (4100)
  └── Example Corp (4200)
        └── Alex Example (4300)   ← leaf / currently-selected
```

Switching the active leaf is done through a UI control on the portal
(not yet reverse-engineered); if you see fewer chargers than expected,
this is likely why. `/relation/BCO/treeview/-1/Relation` is the
starting point for discovering the tree.

## OCPP-like vocabulary

Several state machines mirror OCPP 1.6:

- Connector `State`: `AVAILABLE`, `OCCUPIED`, `RESERVED`, `UNAVAILABLE`,
  `FAULTED`
- Connector `StateDetail` (OCPP status): `Available`, `Preparing`,
  `Charging`, `SuspendedEV`, `SuspendedEVSE`, `Finishing`, `Reserved`,
  `Unavailable`, `Faulted`
- Session `StartReason` / `StopReason`: `OLDCPMSEVENT`, `STOPTRANSACTION`,
  `Remote`, `Local`, `DeAuthorized`, `PowerLoss`, …

Useful for mapping to HA `sensor.state` values with friendly names.

---

## Adding a new endpoint

1. Open the Belgian portal, watch your browser devtools Network tab,
   reproduce the action, and copy the request URL, method, body, and
   response.
2. Add the path under the right section above with a ✅/❓/🔒 marker.
3. Add a typed method on `BlinkChargingClient` in
  `src/blinkcharging_be_eva_portal/client.py`. It should call `self._request()` so
   it inherits auth, retry-on-401, and error-envelope handling for
   free.
4. If the response is a new shape, add a dataclass in
  `src/blinkcharging_be_eva_portal/models.py` with a lenient `from_dict` (use the
   `_as_int` / `_as_float` / `_parse_dt` helpers for empty-string
   tolerance).
5. Keep the full raw dict on the model (`raw: dict[str, Any]`) so
   consumers can reach unmapped fields without a library release.

## Open questions / TODO

- How to switch the active relation on multi-org users?
- Does the portal expose a tariff/cost endpoint per session?
- Any notification/webhook endpoint for real-time session updates, or
  is polling the only option?
- Where is the "set max charging current" control wired — likely a
  variant of `/chargepoint/BCO/Update`.
- Write endpoints for `PlugAndCharge` / `GuestCharging` / `WhiteListing`
  (see `/chargepoint/BCO/{id}/Settings`). The presumed POST targets are
  `/update/isplugandcharge` and `/update/guestcharging` — bodies not
  yet captured.
- The `/user/BCO/*` "UserDetails/Prefs" endpoint (exact path not yet
  captured from devtools) — likely the settings page backing store.
- Correct query params for
  `/relation/BCO/{id}/subscriptiontype/list/filtered` to avoid its
  `<DIVIDE>` error.
