"""Constants for the Rocco's Pizza integration."""
from __future__ import annotations

from datetime import timedelta

DOMAIN = "roccos"

CONF_HOSTNAME = "hostname"
CONF_USERNAME = "username"
CONF_PASSWORD = "password"

# OAuth / androweb constants (public client, implicit flow).
CLIENT_ID = "androweb-website"
SCOPE = "openid customers.read customers.write orders.read orders.write identity.read"
USER_AGENT = "home-assistant-roccos/0.1"

# Regenerate the token when fewer than this many seconds remain.
TOKEN_REFRESH_MARGIN = 600

# Poll fast while an order is in progress, slowly otherwise.
SCAN_INTERVAL_IDLE = timedelta(minutes=30)
SCAN_INTERVAL_ACTIVE = timedelta(seconds=45)

# Order statuses that mean the order is finished (everything else = "live").
DONE_STATUSES = {"completed", "cancelled", "canceled", "rejected", "refunded", "failed"}
