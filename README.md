# roccos-orders

Scrape your own order history from the Rocco's Pizza (Hythe) customer site
(`hythe.roccospizza.co.uk`, an Andromeda POS "androweb" storefront), including
a live-order view. Pure Python stdlib — no dependencies.

## How it works

The site is an Angular SPA; order data comes from a JSON API and is gated behind
an OpenID Connect **implicit-flow** login. Two scripts:

- **`roccos_token.py`** — scripts the identity-first login (email step → password
  step) against IdentityServer, pulls the token out of the redirect fragment, and
  caches it on disk (`.token_cache.json`) with an obtained-at timestamp. Reused
  until <10 min remain, then a fresh login happens automatically.
- **`roccos_orders.py`** — gets a valid token, then calls
  `GET /tenants/{tenant}/orders?CustomerExternalId={id}&CustomerId={id}`
  (customer id = your identity `sub`). Enriches each order with its basket line
  items. Self-heals on a `401`/`403` by forcing a token refresh and retrying once.

## Setup

```sh
cp .env.example .env      # then fill in ROCCOS_PASS
```

`.env`, `.token_cache.json`, and scraped output are gitignored.

## Usage

```sh
python3 roccos_orders.py            # full history as JSON
python3 roccos_orders.py --latest   # most recent order, with items
python3 roccos_orders.py --recent 5 # the N most recent orders, with items
python3 roccos_orders.py --live     # in-progress orders only, with items
python3 roccos_orders.py --only-live [--csv]
python3 roccos_orders.py --csv      # flat table (Live column flags active orders)
python3 roccos_orders.py --force    # ignore cache, log in fresh

python3 roccos_token.py             # print an access token (uses/updates cache)
python3 roccos_token.py --status    # cache state, no network call
python3 roccos_token.py --json      # full cached entry
```

Credentials are read from `.env` (or `ROCCOS_USER` / `ROCCOS_PASS` in the
environment). Nothing is echoed except the token/output; the cache file is
written `chmod 600`.

## Locations

Rocco's runs several storefronts, each on its own `*.roccospizza.co.uk` subdomain.
`roccos_locations.py` scrapes the public
[locations page](https://www.roccospizza.co.uk/locations/) and resolves each
site's API base + tenant id:

```sh
python3 roccos_locations.py --table        # human-readable
python3 roccos_locations.py -o locations.json
```

Discovered sites (as of last run):

| Hostname | Tenant id | Verified |
| --- | --- | --- |
| hythe.roccospizza.co.uk | `0ZjpsCY2NU2nEwQpsLGgqA` | ✅ end-to-end |
| blackwater.roccospizza.co.uk | `PQNpFadc8024LjwgTa1Flw` | discovered only |
| chandlers-ford.roccospizza.co.uk | `JPwNX3kr7EaATaNNKsA8tA` | discovered only |
| greenford.roccospizza.co.uk | `71ciAXG340Gt4WYuknpYLQ` | discovered only |
| ickenham.roccospizza.co.uk | `V5YsuBsih0i5iDXvdws02A` | discovered only |
| slough.roccospizza.co.uk | `IeV3leqsxkWQbsSU7HWDgQ` | discovered only |

> **Only Hythe is verified.** This project was built and tested solely against
> `hythe.roccospizza.co.uk`; the other locations resolve a tenant but their login
> flow, occasions, and deal handling are **not guaranteed to match**.
>
> **Accounts are per-location.** Each storefront has its own account/identity
> system — a login (and token) does **not** carry across locations. To use another
> site you sign in there separately. In Home Assistant that means **one config
> entry per location**, each with its own credentials (entries dedupe by the
> per-site customer id, so the same email at two sites is two distinct accounts).

## Home Assistant integration

A custom component lives in [`custom_components/roccos/`](custom_components/roccos).
It reuses the same login flow (ported to async `aiohttp`) and exposes your orders
as entities.

**Install:** copy `custom_components/roccos/` into your HA `config/custom_components/`
directory, restart, then **Settings → Devices & Services → Add Integration →
Rocco's Pizza** and sign in with your email + password. The site hostname defaults
to `hythe.roccospizza.co.uk` (change it for another Rocco's/androweb site — the
tenant is resolved automatically from the hostname).

**Entities:**

| Entity | Type | Value |
| --- | --- | --- |
| `sensor.roccos_latest_order` | sensor | Status of your most recent order (`OutForDelivery`, `Completed`, `none`); attributes: total, occasion, placed time, live-order count |
| `binary_sensor.roccos_order_active` | binary_sensor (running) | On while any order is in progress; attributes list the live statuses/ids |

The coordinator polls every 30 min when idle and every 45 s while an order is
live. Token handling (cache, refresh, 401 self-heal) matches the CLI. Automate
off `binary_sensor.roccos_order_active` turning on, or the latest-order sensor
changing to `OutForDelivery`.

> Unofficial, reverse-engineered API — for personal use with your own account.

## Notes

- Tenant is hard-coded to Rocco's Pizza – Hythe (`0ZjpsCY2NU2nEwQpsLGgqA`) in the
  CLI scripts; the HA component resolves it from the hostname instead.
- The server issues long-lived tokens (~90 days), so logins are rare in practice.
- Only your own account's data is accessible — the API scopes the results to the
  authenticated customer.
