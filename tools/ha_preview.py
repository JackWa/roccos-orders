#!/usr/bin/env python3
"""
Debug tool: preview what the Home Assistant sensors would report, without running
Home Assistant. Drives the real async client (custom_components/roccos/api.py),
mirrors the coordinator + sensor value/attribute logic, and prints each entity.

Requires aiohttp (a HA dependency, not needed by the CLI):
    python3 -m venv .venv && .venv/bin/pip install aiohttp
    .venv/bin/python tools/ha_preview.py

Credentials come from the repo-root .env (ROCCOS_USER / ROCCOS_PASS), or the
environment. Override the site with ROCCOS_HOSTNAME.

NOTE: the value/attribute formulas below mirror custom_components/roccos/sensor.py
(which can't be imported without Home Assistant). Keep them in sync when sensors change.
"""
import asyncio
import importlib.util
import os
import sys
import types
from datetime import datetime

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COMPONENT = os.path.join(REPO, "custom_components", "roccos")


def load_api():
    """Import roccos.const + roccos.api without executing the package __init__
    (which imports Home Assistant)."""
    pkg = types.ModuleType("roccos")
    pkg.__path__ = [COMPONENT]
    sys.modules["roccos"] = pkg
    for name in ("const", "api"):
        spec = importlib.util.spec_from_file_location(
            f"roccos.{name}", os.path.join(COMPONENT, f"{name}.py"))
        mod = importlib.util.module_from_spec(spec)
        sys.modules[f"roccos.{name}"] = mod
        spec.loader.exec_module(mod)
    return sys.modules["roccos.api"]


def load_env():
    path = os.path.join(REPO, ".env")
    if os.path.exists(path):
        for line in open(path):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k, v.strip().strip('"').strip("'"))


def default_address(customer):
    contacts = customer.get("Contacts") or []
    for c in contacts:
        if c.get("IsDefault"):
            return c
    for c in contacts:
        if (c.get("AddressLine1") or "").strip(" -"):
            return c
    return contacts[0] if contacts else None


def format_address(c):
    parts = [c.get("AddressLine1"), c.get("AddressLine2"), c.get("Town"), c.get("PostCode")]
    return ", ".join(p for p in parts if p and p.strip(" -"))


def show(entity, state, attrs=None):
    print(f"\n{entity}")
    print(f"  state: {state}")
    for k, v in (attrs or {}).items():
        print(f"    {k}: {v}")


async def main():
    load_env()
    api = load_api()
    is_live = api.is_live

    user = os.environ.get("ROCCOS_USER")
    pw = os.environ.get("ROCCOS_PASS")
    if not user or not pw:
        sys.exit("Set ROCCOS_USER / ROCCOS_PASS (or fill the repo-root .env).")
    host = os.environ.get("ROCCOS_HOSTNAME", "hythe.roccospizza.co.uk")

    import aiohttp
    async with aiohttp.ClientSession() as session:
        client = api.RoccosClient(session, host, user, pw)
        await client.async_validate()

        # ---- what the coordinator assembles each poll ----
        orders = await client.async_get_orders()
        orders.sort(key=lambda o: o.get("CreatedTimeUtc", ""), reverse=True)
        customer = await client.async_get_customer()
        item_totals = await client.async_aggregate_items(orders)

        live = [o for o in orders if is_live(o)]
        latest = orders[0] if orders else None
        ranked = sorted(item_totals.items(), key=lambda kv: kv[1], reverse=True)

        print("=" * 64)
        print(f"HA SENSOR PREVIEW  ({host}, live data, no Home Assistant)")
        print("=" * 64)

        show("binary_sensor.roccos_order_active", "on" if live else "off",
             {"count": len(live), "statuses": [o.get("Status") for o in live]})

        show("sensor.roccos_latest_order", latest.get("Status") if latest else "none",
             {"total": latest.get("TotalAmount"), "occasion": latest.get("Occasion"),
              "placed": latest.get("CreatedTimeUtc"), "live_orders": len(live)} if latest else {})

        show("sensor.roccos_order_count", len(orders),
             {"live": len(live), "completed": len(orders) - len(live)})

        show("sensor.roccos_last_order_total", latest.get("TotalAmount") if latest else None,
             {"unit": latest.get("CurrencyCode", "GBP") if latest else None})

        placed = None
        if latest and latest.get("CreatedTimeUtc"):
            placed = datetime.fromisoformat(latest["CreatedTimeUtc"].replace("Z", "+00:00"))
        show("sensor.roccos_last_order_placed", placed.isoformat() if placed else None)

        show("sensor.roccos_total_spend",
             round(sum(float(o.get("TotalAmount") or 0) for o in orders), 2), {"unit": "GBP"})

        show("sensor.roccos_most_ordered_item", ranked[0][0] if ranked else None,
             {"quantity": ranked[0][1] if ranked else 0,
              "top_items": ", ".join(f"{n} ({q})" for n, q in ranked[:5])})

        name = " ".join(p for p in (customer.get("FirstName"), customer.get("LastName")) if p)
        addr = default_address(customer)
        show("sensor.roccos_account", name or customer.get("Email"),
             {"email": customer.get("Email"),
              "default_address": format_address(addr) if addr else None,
              "address_count": len(customer.get("Contacts") or [])})


if __name__ == "__main__":
    asyncio.run(main())
