"""Async client for the Rocco's Pizza (androweb) storefront API.

Handles the IdentityServer implicit-flow login (identity-first: email step then
password step), caches the access token in memory with its expiry, and exposes
the order-history endpoint. Ported from the standalone urllib scripts to aiohttp
so it is safe to run inside Home Assistant's event loop.
"""
from __future__ import annotations

import asyncio
import base64
import html as html_mod
import json
import logging
import re
import secrets
import time
from urllib.parse import parse_qs, urlencode

import aiohttp
from yarl import URL

from .const import (
    CLIENT_ID,
    DONE_STATUSES,
    SCOPE,
    TOKEN_REFRESH_MARGIN,
    USER_AGENT,
)

_LOGGER = logging.getLogger(__name__)

# Where the androweb JSON API lives (same across all androweb storefronts).
CONFIG_PATH = "/api/configuration"


class RoccosAuthError(Exception):
    """Login failed (bad credentials, unexpected flow)."""


class RoccosApiError(Exception):
    """An API request failed."""


def _hidden_fields(page: str) -> dict[str, str]:
    """Extract <input type=hidden> name->value from the first <form> on a page."""
    form = re.search(r"<form\b.*?</form>", page, re.S | re.I)
    scope = form.group(0) if form else page
    fields: dict[str, str] = {}
    for tag in re.findall(r"<input\b[^>]*>", scope, re.I):
        name = re.search(r'name="([^"]*)"', tag, re.I)
        if not name:
            continue
        typ = re.search(r'type="([^"]*)"', tag, re.I)
        val = re.search(r'value="([^"]*)"', tag, re.I)
        if (typ and typ.group(1).lower() == "hidden") or name.group(1) == "__RequestVerificationToken":
            fields[name.group(1)] = html_mod.unescape(val.group(1)) if val else ""
    return fields


def _decode_jwt(token: str) -> dict:
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        return json.loads(base64.urlsafe_b64decode(payload))
    except Exception:  # noqa: BLE001 - opaque/reference tokens are expected
        return {}


def is_live(order: dict) -> bool:
    """True if the order is still in progress (not delivered/collected/cancelled)."""
    return str(order.get("Status", "")).lower() not in DONE_STATUSES


def base_product_name(narrative: str) -> str:
    """Strip a trailing ' (Deal: ...)' suffix so the same product ordered inside
    different deals aggregates together. 'Garlic Sticks (Deal: Big Bite)' -> 'Garlic Sticks'."""
    return re.sub(r"\s*\(Deal:[^)]*\)\s*$", "", narrative).strip()


def basket_item_counts(basket: dict) -> dict[str, int]:
    """Map base product name -> total quantity for one basket (standalone + deal
    items, deal suffix stripped). Pure — no network — so it is unit-testable."""
    counts: dict[str, int] = {}
    if not isinstance(basket, dict):
        return counts

    def walk(items):
        for item in items or []:
            for charge in item.get("Charges", []):
                name = charge.get("Narrative")
                if name:
                    key = base_product_name(name)
                    counts[key] = counts.get(key, 0) + int(charge.get("Quantity", 1) or 1)

    walk(basket.get("Items"))
    for deal in basket.get("Deals", []):
        walk(deal.get("Items"))
    return counts


def basket_summary(basket: dict) -> dict:
    """Per-basket derived numbers, cached once. Pure — unit-testable."""
    if not isinstance(basket, dict):
        return {"items": {}, "deal_savings": 0.0, "delivery_fee": 0.0}
    return {
        "items": basket_item_counts(basket),
        "deal_savings": float(basket.get("DealSavingAmount") or 0),
        "delivery_fee": float(basket.get("DeliveryCharge") or 0),
    }


class RoccosClient:
    """Minimal async client: log in, cache the token, fetch orders."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        hostname: str,
        username: str,
        password: str,
    ) -> None:
        self._session = session  # HA's shared session, used for bearer API calls
        self.hostname = hostname
        self._username = username
        self._password = password

        first, _, rest = hostname.partition(".")
        self._identity = f"https://{first}-identity.{rest}"
        self._headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}

        self._api_base: str | None = None
        self._tenant_id: str | None = None
        self.customer_id: str | None = None

        self._access_token: str | None = None
        self._token_expiry: float = 0.0
        self._lock = asyncio.Lock()

        # basket_id -> basket_summary(); baskets are immutable once placed, so we
        # fetch each at most once.
        self._basket_cache: dict[str, dict] = {}

    # ---- discovery -------------------------------------------------------

    async def _ensure_tenant(self) -> None:
        if self._api_base and self._tenant_id:
            return
        async with self._session.get(
            f"https://{self.hostname}{CONFIG_PATH}", headers=self._headers
        ) as resp:
            cfg = await resp.json(content_type=None)
        self._api_base = cfg["api"]["baseUrl"].rstrip("/")

        async with self._session.get(
            f"{self._api_base}/tenants",
            params={"HostName": self.hostname},
            headers=self._headers,
        ) as resp:
            data = await resp.json(content_type=None)
        tenant = data[0] if isinstance(data, list) else data
        self._tenant_id = tenant["Id"]

    @property
    def _tenant_base(self) -> str:
        return f"{self._api_base}/tenants/{self._tenant_id}"

    # ---- auth ------------------------------------------------------------

    async def _login(self) -> dict:
        """Run the full implicit-flow login; return the token fragment dict."""
        state = secrets.token_urlsafe(24)
        nonce = secrets.token_urlsafe(24)
        authorize = f"{self._identity}/connect/authorize?" + urlencode(
            {
                "response_type": "id_token token",
                "client_id": CLIENT_ID,
                "state": state,
                "redirect_uri": f"https://{self.hostname}/authComplete",
                "scope": SCOPE,
                "nonce": nonce,
            }
        )
        # A dedicated session so the antiforgery cookies never touch HA's shared jar.
        async with aiohttp.ClientSession() as auth:
            async with auth.get(authorize, headers={"User-Agent": USER_AGENT}) as r:
                login_url = str(r.url)
                page = await r.text()
            if "Login" not in login_url:
                raise RoccosAuthError("did not reach the login page")

            # step 1: submit the email -> same page re-renders with a password field
            fields = _hidden_fields(page)
            fields.update({"Username": self._username, "button": "login"})
            async with auth.post(
                login_url, data=fields, headers={"User-Agent": USER_AGENT}
            ) as r:
                page = await r.text()
                if str(r.url).rstrip("/").endswith("/register"):
                    raise RoccosAuthError("account not found for that email")
            if 'name="Password"' not in page:
                raise RoccosAuthError("no password step appeared after the email")

            # step 2: submit email + password
            fields = _hidden_fields(page)
            fields.update(
                {
                    "Username": self._username,
                    "Password": self._password,
                    "button": "login",
                }
            )
            async with auth.post(
                login_url,
                data=fields,
                headers={"User-Agent": USER_AGENT},
                allow_redirects=False,
            ) as r:
                loc = r.headers.get("Location")
            if not loc:
                raise RoccosAuthError("login not accepted (check the password)")

            frag = await self._follow_to_fragment(auth, str(URL(login_url).join(URL(loc))))

        if "access_token" not in frag:
            raise RoccosAuthError("no access_token in the login redirect")
        return frag

    async def _follow_to_fragment(
        self, session: aiohttp.ClientSession, url: str, max_hops: int = 10
    ) -> dict:
        """Walk the redirect chain by hand; parse the #fragment token when we hit it."""
        for _ in range(max_hops):
            async with session.get(
                url, headers={"User-Agent": USER_AGENT}, allow_redirects=False
            ) as r:
                loc = r.headers.get("Location")
            if loc and "#" in loc:
                return {k: v[0] for k, v in parse_qs(loc.split("#", 1)[1]).items()}
            if loc:
                url = str(URL(url).join(URL(loc)))
                continue
            break
        raise RoccosAuthError("token redirect fragment never arrived")

    async def async_get_token(self, force: bool = False) -> str:
        """Return a valid access token, logging in only when needed."""
        async with self._lock:
            if (
                not force
                and self._access_token
                and self._token_expiry - time.time() > TOKEN_REFRESH_MARGIN
            ):
                return self._access_token

            frag = await self._login()
            self._access_token = frag["access_token"]
            self._token_expiry = time.time() + int(frag.get("expires_in", 3600))
            if frag.get("id_token"):
                self.customer_id = _decode_jwt(frag["id_token"]).get("sub")
            _LOGGER.debug("Obtained new Rocco's token, customer %s", self.customer_id)
            return self._access_token

    async def async_validate(self) -> None:
        """Used by the config flow: prove the credentials work."""
        await self._ensure_tenant()
        await self.async_get_token(force=True)
        if not self.customer_id:
            raise RoccosAuthError("logged in but could not determine the customer id")

    # ---- data ------------------------------------------------------------

    async def _get(self, path: str, params: dict | None = None, _retry: bool = True):
        await self._ensure_tenant()
        token = await self.async_get_token()
        headers = {**self._headers, "Authorization": f"Bearer {token}"}
        async with self._session.get(
            f"{self._tenant_base}/{path.lstrip('/')}", params=params, headers=headers
        ) as resp:
            if resp.status in (401, 403) and _retry:
                # cached token revoked server-side: refresh once and retry
                await self.async_get_token(force=True)
                return await self._get(path, params, _retry=False)
            if resp.status != 200:
                body = await resp.text()
                raise RoccosApiError(f"{path} -> HTTP {resp.status}: {body[:200]}")
            return await resp.json(content_type=None)

    async def async_get_orders(self) -> list[dict]:
        data = await self._get(
            "orders",
            {
                "CustomerExternalId": self.customer_id,
                "CustomerId": self.customer_id,
                "pageSize": 100,
            },
        )
        if isinstance(data, dict) and "Items" in data:
            data = data["Items"]
        return data or []

    async def async_get_basket_items(self, basket_id: str) -> list[str]:
        """Flat 'Nx Name' lines for an order's basket (standalone + deal items)."""
        if not basket_id:
            return []
        try:
            basket = await self._get(f"baskets/{basket_id}")
        except RoccosApiError:
            return []
        lines: list[str] = []

        def walk(items):
            for item in items or []:
                for charge in item.get("Charges", []):
                    if charge.get("Narrative"):
                        lines.append(f"{charge.get('Quantity', 1)}x {charge['Narrative']}")

        walk(basket.get("Items"))
        for deal in basket.get("Deals", []):
            walk(deal.get("Items"))
        return lines

    async def async_get_customer(self) -> dict:
        """The customer record: name, email, Contacts (addresses), LoyaltyState."""
        try:
            return await self._get(f"customers/{self.customer_id}")
        except RoccosApiError:
            return {}

    async def async_basket_totals(self, orders: list[dict]) -> dict:
        """Aggregate across all orders' baskets (each fetched at most once):
        per-product quantities, lifetime deal savings, and delivery fees paid."""
        item_totals: dict[str, int] = {}
        deal_savings = 0.0
        delivery_fees = 0.0
        for order in orders:
            basket_id = order.get("BasketId")
            if not basket_id:
                continue
            if basket_id not in self._basket_cache:
                try:
                    basket = await self._get(f"baskets/{basket_id}")
                except RoccosApiError:
                    basket = {}
                self._basket_cache[basket_id] = basket_summary(basket)
            summary = self._basket_cache[basket_id]
            for name, qty in summary["items"].items():
                item_totals[name] = item_totals.get(name, 0) + qty
            deal_savings += summary["deal_savings"]
            delivery_fees += summary["delivery_fee"]
        return {
            "item_totals": item_totals,
            "deal_savings": round(deal_savings, 2),
            "delivery_fees": round(delivery_fees, 2),
        }
