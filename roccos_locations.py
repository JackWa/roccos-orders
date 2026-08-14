#!/usr/bin/env python3
"""
Discover ("propagate") Rocco's Pizza locations from the public locations page.

Scrapes https://www.roccospizza.co.uk/locations/ for storefront subdomains, then
for each resolves the androweb API base URL (/api/configuration) and the tenant id
(/tenants?HostName=...). Emits a locations map as JSON (default) or a table (--table).

IMPORTANT: only `hythe.roccospizza.co.uk` has been verified end-to-end (login +
orders) for this project. Every other site is discovered but UNVERIFIED — the API
shape, occasions, or deal handling may differ. Each entry carries a `verified` flag.

Accounts are NOT portable across locations: each storefront has its own tenant and
its own account/identity system, so a login (and token) is valid only for the site
it was created on. To use another location you register/sign in there separately.

Usage:
  python3 roccos_locations.py            # JSON to stdout
  python3 roccos_locations.py --table    # human-readable table
  python3 roccos_locations.py -o locations.json
"""
import json
import re
import sys
import urllib.parse
import urllib.request

LOCATIONS_URL = "https://www.roccospizza.co.uk/locations/"
BASE_DOMAIN = "roccospizza.co.uk"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"

# Sites confirmed working end-to-end by this project.
VERIFIED = {"hythe.roccospizza.co.uk"}

# Non-storefront subdomains to skip.
SKIP = {"www", "static", "assets", "cdn", "mail", "blog"}


def _get(url, as_json=False, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        body = r.read().decode("utf-8", "replace")
    return json.loads(body) if as_json else body


def discover_hosts():
    """Return sorted storefront hostnames found on the locations page."""
    html = _get(LOCATIONS_URL)
    subs = set(re.findall(rf"https?://([a-z0-9-]+)\.{re.escape(BASE_DOMAIN)}", html))
    return sorted(f"{s}.{BASE_DOMAIN}" for s in subs if s not in SKIP)


def resolve(host):
    """Resolve a storefront's API base + tenant. Returns a location dict."""
    entry = {
        "hostname": host,
        "name": None,
        "tenant_id": None,
        "api_base": None,
        "environment": None,
        "verified": host in VERIFIED,
        "reachable": False,
        "error": None,
    }
    try:
        cfg = _get(f"https://{host}/api/configuration", as_json=True)
        entry["api_base"] = cfg.get("api", {}).get("baseUrl", "").rstrip("/") or None
        entry["environment"] = cfg.get("local", {}).get("environment")
        if entry["api_base"]:
            q = urllib.parse.urlencode({"HostName": host})
            tenants = _get(f"{entry['api_base']}/tenants?{q}", as_json=True)
            tenant = tenants[0] if isinstance(tenants, list) else tenants
            if tenant:
                entry["tenant_id"] = tenant.get("Id")
                entry["name"] = tenant.get("Name") or tenant.get("DisplayName")
        entry["reachable"] = bool(entry["tenant_id"])
    except Exception as e:  # noqa: BLE001 - report per-site, keep going
        entry["error"] = f"{type(e).__name__}: {e}"
    return entry


def main():
    argv = sys.argv[1:]
    out_path = None
    if "-o" in argv:
        out_path = argv[argv.index("-o") + 1]

    hosts = discover_hosts()
    print(f"# discovered {len(hosts)} storefront(s) on the locations page", file=sys.stderr)
    locations = [resolve(h) for h in hosts]

    if "--table" in argv:
        print(f"{'HOSTNAME':32} {'TENANT ID':24} {'ENV':11} VERIFIED  NAME")
        for x in locations:
            flag = "yes" if x["verified"] else ("--" if x["reachable"] else "UNREACHABLE")
            print(f"{x['hostname']:32} {str(x['tenant_id']):24} "
                  f"{str(x['environment']):11} {flag:9} {x['name'] or ''}")
    else:
        payload = json.dumps(locations, indent=2)
        if out_path:
            with open(out_path, "w") as f:
                f.write(payload + "\n")
            print(f"# wrote {len(locations)} locations to {out_path}", file=sys.stderr)
        else:
            print(payload)


if __name__ == "__main__":
    main()
