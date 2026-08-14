#!/usr/bin/env python3
"""
Scrape Rocco's Pizza (Hythe) order history via the androweb API.

Gets an access token (via roccos_token.py — env/.env creds), reads the customer id
from it, then calls the orders endpoint and prints the history. Run with --help for
the full option list.

A SELECTOR chooses which orders (--latest / --recent N / --live / default all);
a FORMAT chooses how to print them (default human summary, or --json / --csv).
The two compose freely.

Examples:
  python3 roccos_orders.py                 # summary of all orders
  python3 roccos_orders.py --latest        # summary of the most recent order
  python3 roccos_orders.py --recent 5      # summary of the 5 most recent orders
  python3 roccos_orders.py --live          # summary of in-progress orders
  python3 roccos_orders.py --live --json   # in-progress orders as JSON
  python3 roccos_orders.py --csv           # all orders as a CSV table
  ROCCOS_TOKEN=eyJ... python3 roccos_orders.py   # reuse a token you already have
"""
import argparse, csv, json, os, sys, urllib.error, urllib.parse, urllib.request
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


def basket_lines(basket):
    """Flatten a basket dict into 'Nx Name £total' lines (standalone items plus
    items bundled inside deals). Pure — no network — so it is unit-testable."""
    if not isinstance(basket, dict):
        return []
    lines = []

    def walk(items):
        for it in items or []:
            for c in it.get("Charges", []):
                if c.get("Narrative"):
                    lines.append(f'{c.get("Quantity", 1)}x {c["Narrative"]}'
                                 + (f'  £{c["Total"]}' if c.get("Total") else ""))
    walk(basket.get("Items"))
    for d in basket.get("Deals", []):
        walk(d.get("Items"))
    return lines


def fetch_basket_items(token, basket_id):
    """Fetch an order's basket and return its flattened item lines."""
    status, basket = api_get(f"baskets/{basket_id}", token)
    if status != 200:
        return []
    return basket_lines(basket)


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


def parse_args(argv=None):
    p = argparse.ArgumentParser(
        description="Scrape Rocco's Pizza (Hythe) order history via the androweb API. "
                    "A selector chooses which orders; a format chooses how to print them.")
    selector = p.add_mutually_exclusive_group()
    selector.add_argument("--latest", action="store_true",
                          help="the single most recent order")
    selector.add_argument("--recent", type=int, metavar="N",
                          help="the N most recent orders")
    selector.add_argument("--live", action="store_true",
                          help="only in-progress orders")
    fmt = p.add_mutually_exclusive_group()
    fmt.add_argument("--json", action="store_true",
                     help="output JSON (default is a human-readable summary)")
    fmt.add_argument("--csv", action="store_true",
                     help="output a flat CSV table")
    p.add_argument("--force", action="store_true",
                   help="ignore the cached token and log in fresh")
    args = p.parse_args(argv)
    if args.recent is not None and args.recent < 1:
        p.error("--recent needs a positive number, e.g. --recent 5")
    return args


def acquire_token(force):
    """Return (token, cid, user, pw), exiting cleanly on any login failure."""
    env_token = os.environ.get("ROCCOS_TOKEN")
    if env_token:
        return env_token, os.environ.get("ROCCOS_CID"), None, None
    here = os.path.dirname(os.path.abspath(__file__))
    rt.load_dotenv(os.environ.get("ROCCOS_ENV", os.path.join(here, ".env")))
    user = os.environ.get("ROCCOS_USER")
    pw = os.environ.get("ROCCOS_PASS")
    try:
        token, cid = rt.get_valid_token(user, pw, force=force)
    except Exception as err:  # noqa: BLE001 - clean message, not a traceback
        print(f"ERROR: login failed: {err}", file=sys.stderr)
        sys.exit(3)
    return token, cid, user, pw


def main(argv=None):
    args = parse_args(argv)

    # Token via the on-disk cache: reused until <10 min left, then re-logged in.
    token, cid, user, pw = acquire_token(args.force)
    if not cid:
        print("ERROR: no customer id (set ROCCOS_CID, or let login supply the id_token)",
              file=sys.stderr)
        sys.exit(2)
    print(f"# customer id: {cid}", file=sys.stderr)

    status, data = fetch_orders(token, cid)
    # A cached token revoked server-side returns 401/403: refresh once and retry
    # (only when we own the login — a caller-supplied ROCCOS_TOKEN can't be refreshed).
    if status in (401, 403) and user is not None:
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
    if not isinstance(items, list):
        items = []
    items.sort(key=lambda o: o.get("CreatedTimeUtc", ""), reverse=True)
    live_count = sum(1 for o in items if is_live(o))
    print(f"# orders returned: {len(items)} ({live_count} live)", file=sys.stderr)

    # Selector: which orders, plus a heading for the summary format.
    if args.latest:
        selected, heading = items[:1], "Latest order:"
    elif args.recent is not None:
        selected = items[:args.recent]
        heading = f"{len(selected)} most recent order(s):"
    elif args.live:
        selected = [o for o in items if is_live(o)]
        heading = f"{len(selected)} live order(s):"
    else:
        selected, heading = items, f"{len(items)} order(s):"

    # Format: how to print the selected orders.
    if args.json:
        json.dump(selected, sys.stdout, indent=2, ensure_ascii=False)
        print()
    elif args.csv:
        writer = csv.DictWriter(sys.stdout, fieldnames=list(flatten({}).keys()))
        writer.writeheader()
        for order in selected:
            writer.writerow(flatten(order))
    elif args.live and not selected:
        print("No live orders — nothing currently in progress.")
    else:
        print(summarize_orders(token, selected, heading))


if __name__ == "__main__":
    main()
