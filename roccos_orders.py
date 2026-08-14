#!/usr/bin/env python3
"""
Scrape Rocco's Pizza (Hythe) order history via the androweb API.

Gets an access token (via roccos_token.py — env/.env creds), decodes the customer
id from it, then discovers the working orders endpoint against the live API and
dumps the order history as JSON (default) or CSV (--csv).

Usage:
  python3 roccos_orders.py                 # JSON to stdout
  python3 roccos_orders.py --csv           # flat CSV to stdout
  ROCCOS_TOKEN=eyJ... python3 roccos_orders.py   # reuse a token you already have
"""
import os, sys, json, csv, io, urllib.request, urllib.error, urllib.parse
import roccos_token as rt

API = "https://live-androweb-api.azurewebsites.net"
TENANT = "0ZjpsCY2NU2nEwQpsLGgqA"          # Rocco's Pizza - Hythe
BASE = f"{API}/tenants/{TENANT}"


def api_get(path, token, params=None):
    url = f"{BASE}/{path.lstrip('/')}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "User-Agent": rt.UA,
        "x-tenant-id": TENANT,
    })
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read().decode("utf-8", "replace") or "null")
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace") if e.fp else ""
        return e.code, body


# Order statuses that mean the order is still in progress (not yet delivered/collected).
# Anything not in DONE is treated as "live".
DONE = {"completed", "cancelled", "canceled", "rejected", "refunded", "failed"}


def is_live(order):
    return str(order.get("Status", "")).lower() not in DONE


def fetch_orders(token, cid):
    """The orders list endpoint requires BOTH CustomerExternalId and CustomerId
    (same value = the identity sub). Returns (status, data)."""
    return api_get("orders", token, {
        "CustomerExternalId": cid,
        "CustomerId": cid,
        "pageSize": 100,
    })


def fetch_basket_items(token, basket_id):
    """Return a flat list of 'Nx Name £total' lines for an order's basket
    (standalone items + items bundled inside deals)."""
    status, b = api_get(f"baskets/{basket_id}", token)
    if status != 200 or not isinstance(b, dict):
        return []
    lines = []

    def walk(items):
        for it in items or []:
            for c in it.get("Charges", []):
                if c.get("Narrative"):
                    lines.append(f'{c.get("Quantity", 1)}x {c["Narrative"]}'
                                 + (f'  £{c["Total"]}' if c.get("Total") else ""))
    walk(b.get("Items"))
    for d in b.get("Deals", []):
        walk(d.get("Items"))
    return lines


def summarize_orders(token, orders, heading):
    """Human-readable summary of the given orders, each with its line items."""
    if not orders:
        return f"{heading}\n  (none)"
    out = [heading, ""]
    for o in orders:
        out.append(f"● {o.get('Status')}  —  £{o.get('TotalAmount')} {o.get('CurrencyCode','')}"
                   f"  ({o.get('Occasion')})")
        out.append(f"  placed {o.get('CreatedTimeUtc','?')}   order {o.get('Id')}")
        for line in fetch_basket_items(token, o.get("BasketId", "")):
            out.append(f"    - {line}")
        out.append("")
    return "\n".join(out)


def summarize_live(token, orders):
    live = [o for o in orders if is_live(o)]
    if not live:
        return "No live orders — nothing currently in progress."
    return summarize_orders(token, live, f"{len(live)} live order(s):")


def flatten(order):
    """Best-effort flattening of an order record for CSV."""
    def g(*keys):
        for k in keys:
            if isinstance(order, dict) and order.get(k) is not None:
                return order[k]
        return ""
    return {
        "OrderId": g("Id", "OrderId"),
        "PlacedUtc": g("CreatedTimeUtc", "CreatedUtc", "PlacedUtc"),
        "Occasion": g("Occasion"),
        "Status": g("Status"),
        "Live": "yes" if is_live(order) else "",
        "Total": g("TotalAmount", "Total"),
        "Currency": g("CurrencyCode"),
        "Payment": g("PaymentStatus"),
    }


def main():
    # Token via the on-disk cache: reused until <10 min left, then re-logged in.
    env_token = os.environ.get("ROCCOS_TOKEN")
    token = env_token
    cid = os.environ.get("ROCCOS_CID")
    user = pw = None
    if not token:
        here = os.path.dirname(os.path.abspath(__file__))
        rt.load_dotenv(os.environ.get("ROCCOS_ENV", os.path.join(here, ".env")))
        user = os.environ.get("ROCCOS_USER")
        pw = os.environ.get("ROCCOS_PASS")
        try:
            token, cid = rt.get_valid_token(user, pw, force="--force" in sys.argv)
        except Exception as err:  # noqa: BLE001 - surface a clean message, not a traceback
            print(f"ERROR: login failed: {err}", file=sys.stderr)
            sys.exit(3)
    if not cid:
        print("ERROR: no customer id (set ROCCOS_CID, or let login supply the id_token)", file=sys.stderr)
        sys.exit(2)
    print(f"# customer id: {cid}", file=sys.stderr)

    status, data = fetch_orders(token, cid)
    # A cached token that got revoked server-side returns 401/403: refresh once and retry.
    if status in (401, 403) and not env_token:
        print(f"# token rejected ({status}) — refreshing and retrying", file=sys.stderr)
        try:
            token, cid = rt.get_valid_token(user, pw, force=True)
        except Exception as err:  # noqa: BLE001
            print(f"ERROR: re-login after {status} failed: {err}", file=sys.stderr)
            sys.exit(3)
        status, data = fetch_orders(token, cid)
    if status != 200:
        print(f"orders request failed [{status}]: {str(data)[:300]}", file=sys.stderr)
        sys.exit(2)

    items = data.get("Items") if isinstance(data, dict) and "Items" in data else data
    live_count = sum(1 for o in items if is_live(o)) if isinstance(items, list) else 0
    print(f"# orders returned: {len(items) if isinstance(items, list) else '?'} "
          f"({live_count} live)", file=sys.stderr)

    # --recent N: human summary of the N most-recent orders (by placed time)
    if "--recent" in sys.argv and isinstance(items, list):
        i = sys.argv.index("--recent")
        try:
            n = int(sys.argv[i + 1])
        except (IndexError, ValueError):
            print("ERROR: --recent needs a number, e.g. --recent 5", file=sys.stderr)
            sys.exit(2)
        recent = sorted(items, key=lambda o: o.get("CreatedTimeUtc", ""), reverse=True)[:n]
        print(summarize_orders(token, recent, f"{len(recent)} most recent order(s):"))
        return

    # --latest: human summary of the single most-recent order (by placed time)
    if "--latest" in sys.argv and isinstance(items, list) and items:
        newest = max(items, key=lambda o: o.get("CreatedTimeUtc", ""))
        print(summarize_orders(token, [newest], "Latest order:"))
        return

    # --live: human summary of in-progress orders only
    if "--live" in sys.argv:
        print(summarize_live(token, items if isinstance(items, list) else []))
        return

    # --only-live: restrict JSON/CSV output to in-progress orders
    if "--only-live" in sys.argv and isinstance(items, list):
        items = [o for o in items if is_live(o)]
        data = items

    if "--csv" in sys.argv and isinstance(items, list):
        w = csv.DictWriter(sys.stdout, fieldnames=list(flatten(items[0] if items else {}).keys()))
        w.writeheader()
        for o in items:
            w.writerow(flatten(o))
    else:
        json.dump(data, sys.stdout, indent=2, ensure_ascii=False)
        print()


if __name__ == "__main__":
    main()
