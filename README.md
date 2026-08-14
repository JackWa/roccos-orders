# roccos-orders

> ⚠️ **Unofficial, unaffiliated, and totally vibe-coded.**
> This project is **not affiliated with, endorsed by, or supported by Rocco's Pizza**.
> It talks to a **private, undocumented API** (reverse-engineered from the website)
> that can change or break at any time, without notice. The whole thing — CLI,
> Home Assistant integration, the lot — was **"vibe-coded"**: built fast and
> conversationally with an AI assistant against the live site, with light review.
> Treat it as a personal hack, not production software. Use it **only with your own
> account, at your own risk.** Not legal advice; see [Terms & compliance](#terms--compliance).

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
cp .env.example .env      # then set ROCCOS_HOSTNAME, ROCCOS_USER, ROCCOS_PASS
```

`ROCCOS_HOSTNAME` picks the storefront — **there is no default**, so set it in
`.env` (or pass `--site`). Discover the options with `roccos_locations.py`.
Accounts are per-location, so the credentials must match the chosen site. `.env`,
`.token_cache.*.json` (one cache per location), and scraped output are gitignored.

## Usage

A **selector** chooses which orders; a **format** chooses how to print them. They
compose freely, so every selector supports all three formats:

| | summary (default) | `--json` | `--csv` |
| --- | --- | --- | --- |
| _(none)_ = all | `roccos_orders.py` | `--json` | `--csv` |
| `--latest` | `--latest` | `--latest --json` | `--latest --csv` |
| `--recent N` | `--recent 5` | `--recent 5 --json` | `--recent 5 --csv` |
| `--live` | `--live` | `--live --json` | `--live --csv` |

```sh
python3 roccos_orders.py            # summary of all orders (default)
python3 roccos_orders.py --live --json   # in-progress orders as JSON
python3 roccos_orders.py --recent 5 --csv
python3 roccos_orders.py --site slough.roccospizza.co.uk   # override the location
python3 roccos_orders.py --force    # ignore cache, log in fresh
python3 roccos_orders.py --help     # full option list

python3 roccos_token.py             # print an access token (uses/updates cache)
python3 roccos_token.py --status    # cache state, no network call
python3 roccos_token.py --json      # full cached entry
```

Credentials are read from `.env` (or `ROCCOS_USER` / `ROCCOS_PASS` in the
environment). Nothing is echoed except the token/output; the cache file is
written `chmod 600`.

## Examples

Diagnostics print to stderr (the `#` lines); the data itself goes to stdout, so
it pipes cleanly. Customer id shown as `<cust>` below.

**Latest order** — `python3 roccos_orders.py --latest`

```
# using cached token (129594m 20s left)
# customer id: <cust>
# orders returned: 11 (0 live)
Latest order:

● Completed  —  £44.47 GBP  (Delivery)
  placed 2026-08-14T18:30:38.7817656Z   order 9f37d600-8cb3-461a-9118-33f4fd3aa36b
    - 1x Ben & Jerrys - Chocolate Fudge Brownie  £6.49
    - 1x Pizza Madras (Deal: Party Pack - Medium)  £34.99
    - 1x Texas BBQ Chicken (Deal: Party Pack - Medium)
    - 1x Meatball Lovers (Deal: Party Pack - Medium)
    - 1x Chicken Goujons (Deal: Party Pack - Medium)
    - 1x Garlic Sticks (Deal: Party Pack - Medium)
    - 1x Garlic Sticks (Deal: Party Pack - Medium)
    - 1x Pepsi Max - 1.5L Bottle (Deal: Party Pack - Medium)
```

**Live orders** — `python3 roccos_orders.py --live` (nothing in progress)

```
# orders returned: 11 (0 live)
No live orders — nothing currently in progress.
```

While an order is out for delivery the same command shows it with its items and a
`● OutForDelivery — £… (Delivery)` header.

**Flat table** — `python3 roccos_orders.py --csv` (stderr suppressed)

```
OrderId,PlacedUtc,Occasion,Status,Live,Total,Currency,Payment
9f37d600-8cb3-461a-9118-33f4fd3aa36b,2026-08-14T18:30:38.7817656Z,Delivery,OutForDelivery,yes,44.47,GBP,Paid
13aaeb80-93de-4ca7-a586-71b4acf92840,2026-06-12T18:44:57.5449728Z,Collection,Completed,,21.39,GBP,Paid
453FC95F-7B9B-417F-9DE1-B2DD9C553B6E,2025-11-02T12:24:48.4911312Z,Collection,Completed,,73.96,GBP,Paid
...
```

**Token status** — `python3 roccos_token.py --status` (no network call)

```
cached token: 129594m 33s left (valid), customer <cust>
```

**Self-heal** — a revoked/expired cached token triggers a single silent re-login:

```
# using cached token (...)
# token rejected (401) — refreshing and retrying
# regenerating token (forced)
# orders returned: 11 (1 live)
```

## Locations

Rocco's runs several storefronts, each on its own `*.roccospizza.co.uk` subdomain.
`roccos_locations.py` scrapes the public
[locations page](https://www.roccospizza.co.uk/locations/) and resolves each
site's API base + tenant id:

```sh
python3 roccos_locations.py --table        # human-readable
python3 roccos_locations.py -o locations.json
```

Example — `python3 roccos_locations.py --table`:

```
# discovered 6 storefront(s) on the locations page
HOSTNAME                         TENANT ID                ENV         VERIFIED  NAME
blackwater.roccospizza.co.uk     PQNpFadc8024LjwgTa1Flw   Production  --        Rocco's Pizza - Blackwater
chandlers-ford.roccospizza.co.uk JPwNX3kr7EaATaNNKsA8tA   Production  --        Rocco's Pizza - Chandlers Ford
greenford.roccospizza.co.uk      71ciAXG340Gt4WYuknpYLQ   Production  --        Rocco's Pizza - Greenford
hythe.roccospizza.co.uk          0ZjpsCY2NU2nEwQpsLGgqA   Production  yes       Rocco's Pizza - Hythe
ickenham.roccospizza.co.uk       V5YsuBsih0i5iDXvdws02A   Production  --        Rocco's Pizza - Ickenham
slough.roccospizza.co.uk         IeV3leqsxkWQbsSU7HWDgQ   Production  --        Rocco's Pizza - Slough
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
Rocco's Pizza**. The setup dialog shows a **dropdown of discovered locations** —
pick your store, then sign in with that store's email + password (you can also type
a hostname if yours isn't listed). The tenant is resolved automatically.

**Multiple locations:** add the integration **once per location** (accounts are
per-location and don't carry across sites). Each becomes its own device named after
the store — e.g. *Rocco's Pizza - Slough* → `sensor.roccos_pizza_slough_total_spend`
— so several stores coexist without collisions.

**Entities:**

| Entity | Type | Value |
| --- | --- | --- |
| `sensor.roccos_latest_order` | sensor | Status of your most recent order; attributes: total, occasion, placed time, live-order count, `recent_orders` (last 10) |
| `sensor.roccos_order_count` | sensor (total) | Total orders on the account; attributes: live / completed counts |
| `sensor.roccos_last_order_total` | sensor (monetary) | £ total of the most recent order |
| `sensor.roccos_last_order_placed` | sensor (timestamp) | When the most recent order was placed (enables "days since") |
| `sensor.roccos_total_spend` | sensor (monetary) | Lifetime spend — sum of every order |
| `sensor.roccos_average_order_value` | sensor (monetary) | Mean order value (spend ÷ order count) |
| `sensor.roccos_total_deal_savings` | sensor (monetary) | Lifetime £ saved via deals |
| `sensor.roccos_most_ordered_item` | sensor | Product you've ordered most (deal suffixes merged); attribute `top_items` |
| `sensor.roccos_favourite_occasion` | sensor | Your most common occasion; attributes give the counts |
| `sensor.roccos_loyalty_points` | sensor | Loyalty balance — **stays 0 where the scheme isn't active (e.g. Hythe)** |
| `sensor.roccos_account` | sensor (diagnostic) | Your name; attributes: email, default delivery address, address count |
| `binary_sensor.roccos_order_active` | binary_sensor (running) | On while any order is in progress; attributes list the live statuses/ids |

The coordinator fetches your orders + customer record each poll and aggregates
per-product totals across all baskets (each basket fetched once, then cached).

The coordinator polls every 30 min when idle and every 45 s while an order is
live. Token handling (cache, refresh, 401 self-heal) matches the CLI. Automate
off `binary_sensor.roccos_order_active` turning on, or the latest-order sensor
changing to `OutForDelivery`.

> Unofficial, reverse-engineered API — for personal use with your own account.

## Failure handling

**CLI** — a failed login or re-login prints a clean, single-line reason to stderr
and exits non-zero (no Python traceback):

```
ERROR: login failed: login not accepted: Invalid email or password.   # exit 3
ERROR: re-login after 401 failed: ...                                  # exit 3
```

Exit codes: `2` = bad request / missing customer id, `3` = auth failure.

**Home Assistant** — the coordinator distinguishes two failures:

- API/network error (`RoccosApiError`) → `UpdateFailed`: entities go
  *unavailable* and HA retries on the next poll.
- Login/re-login failure (`RoccosAuthError`, e.g. you changed your password) →
  `ConfigEntryAuthFailed`: HA marks the entry as needing attention and opens the
  **reauth flow**, prompting you to re-enter the password for that account.

## Development

Pure helpers (order classification, CSV flattening, basket parsing, JWT decoding,
antiforgery-field extraction, arg parsing) have no-network unit tests:

```sh
python3 -m unittest discover -s tests
```

CLI options are parsed with `argparse` — run `python3 roccos_orders.py --help`.

**Preview the HA sensors without Home Assistant** — `tools/ha_preview.py` drives
the real async client and prints what each entity would report:

```sh
python3 -m venv .venv && .venv/bin/pip install aiohttp
.venv/bin/python tools/ha_preview.py
```

It reads creds from the repo-root `.env`. (The formulas mirror `sensor.py`, which
can't be imported without Home Assistant — keep them in sync when sensors change.)

## Terms & compliance

**Terms reviewed 2026-08-14** — <https://www.roccospizza.co.uk/terms/>.

The published T&Cs cover food ordering (payment, ~45-minute delivery aim, refund
and cancellation policy) and a privacy policy (cookies, Google Analytics). As of
that date they contain **no** clause restricting automated/programmatic access,
scraping, reverse engineering, use of non-official clients, or API use, and set
out no developer terms or rate limits. The privacy policy affirms a user's right
to access their own personal data.

This tool only reads **your own authenticated account's** data (orders, profile,
addresses), never anyone else's, and places no orders — so nothing in the current
terms appears to prohibit this personal use. It stays deliberately low-impact:
tokens and per-order baskets are cached, and polling backs off to 30 minutes when
idle. This is a good-faith reading, **not legal advice**; the terms can change, so
re-check periodically and keep usage personal and low-volume.

## Notes

- Tenant is hard-coded to Rocco's Pizza – Hythe (`0ZjpsCY2NU2nEwQpsLGgqA`) in the
  CLI scripts; the HA component resolves it from the hostname instead.
- The server issues long-lived tokens (~90 days), so logins are rare in practice.
- Only your own account's data is accessible — the API scopes the results to the
  authenticated customer.
