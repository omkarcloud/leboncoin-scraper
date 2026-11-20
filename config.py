"""Configuration for the Leboncoin Scraper. Everything can be set with an environment
variable; the defaults work out of the box.

    PORT              port the API listens on (default 8000)
    LEBONCOIN_PROXY   proxy URL for every request, e.g. http://user:pass@host:port
                      (default: none, requests go out from your own connection)

Leboncoin works from your own connection, no proxy needed. If Leboncoin starts
refusing you at volume, set LEBONCOIN_PROXY to a French residential proxy.

Everything else below is a plain constant with a working default.
"""
import os

PORT = int(os.environ.get("PORT", "8000"))

LEBONCOIN_PROXY = os.environ.get("LEBONCOIN_PROXY") or None


# ---- what the code reads off config: defaults for a direct run ----
LEBONCOIN_API_KEY = "ba0c2dad52b3ec"   # the public api_key header Leboncoin's own pages and apps send; search is refused without it
LEBONCOIN_APP_OS_VERSION = '18.5'      # the iOS version the app user-agent names
LEBONCOIN_APP_VERSION = '101.45.0'     # the Leboncoin app version the user-agent names
LEBONCOIN_BLOCK_COOLDOWN = 900
LEBONCOIN_EXIT = LEBONCOIN_PROXY      # the exit every session leaves through: your proxy, or direct
LEBONCOIN_FALLBACK_EXITS = ()         # no exit behind yours: set LEBONCOIN_PROXY to change where requests leave from
LEBONCOIN_GATEWAY_REFUSALS = 6
MAX_RETRIES = 3
RETRY_BACKOFF = 2
def gateway_exit(exit=None):
    return None

