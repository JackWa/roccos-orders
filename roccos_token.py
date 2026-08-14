#!/usr/bin/env python3
"""
Generate an OAuth access token for a Rocco's Pizza storefront (set by
ROCCOS_HOSTNAME) by scripting the IdentityServer implicit-flow login.

Flow (identity-first, single URL, two POSTs):
  1. GET /connect/authorize  -> 302 -> /Account/Login (antiforgery cookie + hidden token)
  2. POST Username            -> same page re-rendered WITH a Password field
  3. POST Username+Password   -> 302 chain -> redirect_uri#access_token=...&id_token=...
The tokens come back in the URL *fragment* (response_mode=fragment), so we walk the
redirect chain by hand and stop at the fragment.

Credentials come from env (ROCCOS_USER / ROCCOS_PASS) or an interactive prompt.
Nothing is written to disk and nothing is echoed except the token(s).
"""
import os, sys, re, json, time, base64, secrets, getpass
import urllib.parse, urllib.request
from http.cookiejar import CookieJar

REFRESH_MARGIN = 600  # regenerate when fewer than this many seconds remain (10 min)

CLIENT_ID = "androweb-website"
SCOPE = "openid customers.read customers.write orders.read orders.write identity.read"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"

NO_HOSTNAME = ("no storefront hostname — set ROCCOS_HOSTNAME (e.g. in .env) or pass --site, "
               "e.g. hythe.roccospizza.co.uk")


def resolve_hostname(hostname=None):
    """The storefront hostname from an explicit arg or $ROCCOS_HOSTNAME. No default —
    returns None if neither is set (callers must handle that)."""
    return hostname or os.environ.get("ROCCOS_HOSTNAME")


def identity_url(hostname):
    """hythe.roccospizza.co.uk -> https://hythe-identity.roccospizza.co.uk"""
    first, _, rest = hostname.partition(".")
    return f"https://{first}-identity.{rest}"


def cache_path(hostname):
    """Per-location token cache (override with $ROCCOS_CACHE)."""
    if os.environ.get("ROCCOS_CACHE"):
        return os.environ["ROCCOS_CACHE"]
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(here, f".token_cache.{hostname.split('.')[0]}.json")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    """Capture 3xx Location instead of following it."""
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # -> urllib raises HTTPError, whose .headers has Location


def build_opener():
    cj = CookieJar()
    op = urllib.request.build_opener(NoRedirect, urllib.request.HTTPCookieProcessor(cj))
    op.addheaders = [("User-Agent", UA)]
    return op


def _open(op, url, data=None):
    """Return (status, final_url, location_or_None, body_text)."""
    req = urllib.request.Request(url, data=data, method="POST" if data else "GET")
    try:
        r = op.open(req)
        body = r.read().decode("utf-8", "replace")
        return r.status, r.geturl(), None, body
    except urllib.error.HTTPError as e:
        loc = e.headers.get("Location")
        body = e.read().decode("utf-8", "replace") if e.fp else ""
        return e.code, url, loc, body


def follow(op, url, max_hops=10):
    """Follow redirects manually; stop when a Location carries a #fragment
    (implicit-flow token) or when we run out of redirects. Returns (status, url, loc, body)."""
    for _ in range(max_hops):
        status, cur, loc, body = _open(op, url)
        if loc and "#" in loc:
            return status, cur, loc, body
        if loc:
            url = urllib.parse.urljoin(cur, loc)
            continue
        return status, cur, loc, body
    raise RuntimeError("too many redirects")


def hidden_fields(html):
    """All <input type=hidden> name->value from the first <form>."""
    form = re.search(r"<form\b.*?</form>", html, re.S | re.I)
    scope = form.group(0) if form else html
    fields = {}
    for m in re.finditer(r'<input\b[^>]*>', scope, re.I):
        tag = m.group(0)
        t = re.search(r'type="([^"]*)"', tag, re.I)
        n = re.search(r'name="([^"]*)"', tag, re.I)
        v = re.search(r'value="([^"]*)"', tag, re.I)
        if not n:
            continue
        if (t and t.group(1).lower() == "hidden") or n.group(1) in ("__RequestVerificationToken",):
            import html as _h
            fields[n.group(1)] = _h.unescape(v.group(1)) if v else ""
    return fields


def decode_jwt(tok):
    """Return a JWT's claims, or {} for an opaque/reference token."""
    try:
        p = tok.split(".")[1]
        p += "=" * (-len(p) % 4)
        return json.loads(base64.urlsafe_b64decode(p))
    except Exception:
        return {}


def get_token(user, pw, hostname=None):
    host = resolve_hostname(hostname)
    if not host:
        raise RuntimeError(NO_HOSTNAME)
    op = build_opener()
    st = secrets.token_urlsafe(24)
    nn = secrets.token_urlsafe(24)
    authorize = f"{identity_url(host)}/connect/authorize?" + urllib.parse.urlencode({
        "response_type": "id_token token", "client_id": CLIENT_ID,
        "state": st, "redirect_uri": f"https://{host}/authComplete", "scope": SCOPE, "nonce": nn,
    }, quote_via=urllib.parse.quote)

    # 1) authorize -> login page
    status, login_url, loc, html = follow(op, authorize)
    if "Login" not in login_url:
        raise RuntimeError(f"expected login page, got {login_url}")

    # 2) POST email; the same URL re-renders with a Password field
    f = hidden_fields(html)
    f["Username"] = user
    f["button"] = "login"
    status, url2, loc, html = _open(op, login_url, urllib.parse.urlencode(f).encode())
    if loc:  # unexpected redirect (e.g. /register = unknown account)
        raise RuntimeError(f"after email the server redirected to {loc} "
                           f"(account may not exist / passwordless)")
    if 'name="Password"' not in html:
        raise RuntimeError("no Password field appeared after submitting the email")

    # 3) POST email+password
    f = hidden_fields(html)          # fresh antiforgery token + AskForPassword etc.
    f["Username"] = user
    f["Password"] = pw
    f["button"] = "login"
    status, url3, loc, html = _open(op, login_url, urllib.parse.urlencode(f).encode())
    if not loc:
        msg = re.search(r'validation-summary[^>]*>(.*?)</div>', html, re.S)
        hint = re.sub(r"<[^>]+>|\s+", " ", msg.group(1)).strip() if msg else "no redirect (bad credentials?)"
        raise RuntimeError(f"login not accepted: {hint}")

    # follow authorize/callback chain to the token fragment
    nexturl = urllib.parse.urljoin(url3, loc)
    status, cur, loc, body = follow(op, nexturl)
    if not (loc and "#" in loc):
        raise RuntimeError("did not reach the token redirect")
    frag = urllib.parse.parse_qs(loc.split("#", 1)[1])
    if "access_token" not in frag:
        raise RuntimeError(f"no access_token in fragment: {loc.split('#',1)[1][:120]}")
    return {k: v[0] for k, v in frag.items()}


def load_dotenv(path):
    """Minimal .env loader: KEY=VALUE lines, optional quotes, # comments.
    Does not overwrite variables already set in the real environment."""
    if not os.path.exists(path):
        return
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip().strip('"').strip("'")
        os.environ.setdefault(k, v)


def _read_cache(path):
    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, ValueError):
        return None


def _write_cache(frag, path):
    """Persist the token fragment plus obtained_at (epoch) and the decoded customer id."""
    entry = dict(frag)
    entry["obtained_at"] = int(time.time())
    entry["expires_in"] = int(frag.get("expires_in", 3600))
    if frag.get("id_token"):
        entry["customer_id"] = (decode_jwt(frag["id_token"]) or {}).get("sub")
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(entry, f)
    os.chmod(tmp, 0o600)     # token on disk -> owner-only
    os.replace(tmp, path)    # atomic
    return entry


def seconds_left(entry):
    if not entry:
        return -1
    return entry.get("obtained_at", 0) + entry.get("expires_in", 0) - int(time.time())


def get_valid_token(user=None, pw=None, hostname=None, margin=REFRESH_MARGIN, force=False):
    """Return (access_token, customer_id), reusing the per-location cached token
    unless it has fewer than `margin` seconds left (or force). Regenerating needs creds."""
    host = resolve_hostname(hostname)
    if not host:
        raise RuntimeError(NO_HOSTNAME)
    path = cache_path(host)
    entry = _read_cache(path)
    left = seconds_left(entry)
    if entry and not force and left > margin:
        print(f"# using cached token for {host} ({left//60}m {left%60}s left)", file=sys.stderr)
        return entry["access_token"], entry.get("customer_id")

    reason = "forced" if force else ("no cache" if not entry else f"{left}s left <= {margin}s")
    print(f"# regenerating token for {host} ({reason})", file=sys.stderr)
    if not user:
        raise RuntimeError("token expired and no credentials available to regenerate")
    frag = get_token(user, pw, host)
    entry = _write_cache(frag, path)
    return entry["access_token"], entry.get("customer_id")


def main():
    # look for a .env next to this script (or ROCCOS_ENV=/path/to/.env)
    here = os.path.dirname(os.path.abspath(__file__))
    load_dotenv(os.environ.get("ROCCOS_ENV", os.path.join(here, ".env")))
    host = resolve_hostname()
    if not host:
        print(f"ERROR: {NO_HOSTNAME}", file=sys.stderr)
        sys.exit(2)
    path = cache_path(host)

    # --status: report cache state without touching the network
    if "--status" in sys.argv:
        entry = _read_cache(path)
        left = seconds_left(entry)
        if not entry:
            print(f"no cached token for {host}", file=sys.stderr)
        else:
            print(f"cached token for {host}: {left//60}m {left%60}s left "
                  f"({'valid' if left > REFRESH_MARGIN else 'stale — will refresh'}), "
                  f"customer {entry.get('customer_id')}", file=sys.stderr)
        return

    user = os.environ.get("ROCCOS_USER") or input("Email: ").strip()
    pw = os.environ.get("ROCCOS_PASS") or getpass.getpass("Password: ")
    try:
        # honours the cache; --force ignores it and logs in fresh
        token, cid = get_valid_token(user, pw, force="--force" in sys.argv)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)

    if "--json" in sys.argv:
        print(json.dumps(_read_cache(path), indent=2))
    else:
        print(token)


if __name__ == "__main__":
    main()
