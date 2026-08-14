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

## Notes

- Tenant is hard-coded to Rocco's Pizza – Hythe (`0ZjpsCY2NU2nEwQpsLGgqA`).
- The server issues long-lived tokens (~90 days), so logins are rare in practice.
- Only your own account's data is accessible — the API scopes the results to the
  authenticated customer.
