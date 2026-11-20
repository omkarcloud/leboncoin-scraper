"""Leboncoin transport: plain curl_cffi on api.leboncoin.fr, the JSON API
behind the site and its mobile app. No browser, no login, no cookie minted
anywhere.

The whole site sits behind DataDome. A call that looks like the web page
(chrome TLS, the page's origin / referer) is answered with a challenge
unless it carries a cookie a real browser earned. A call that looks like
the mobile app passes with nothing else (research and pod probe 2026-11-20):

  * the app's user-agent   LBC;iOS;<os>;iPhone;phone;<device uuid>;wifi;<app version>
  * a Safari TLS profile   safari_ios (safari17_0 passes too; chrome is refused)
  * api_key                the public key the site's own pages send (without
                           it the search call is refused)
  * accept                 application/json (the reference data call is
                           refused without it, 0 of 3 against 3 of 3)
  * NO web headers         the page's origin / referer next to the app's
                           user-agent is refused

Surfaces used (each answered 200 from the pod's own IP):

  POST /finder/search                              search, a seller's ads, and
       ads by id: a `pivot` naming `ids_to_display` answers exactly those
       ads in full, up to 100 a call; an id the site does not have is left out
  GET  /api/vs-recommendation-api/v1/search/<id>   visually similar ads (404: unknown ad)
  GET  /api/user-card/v2/<user id>/infos           a seller's card (404: unknown user)
  GET  /api/users/v1/users/pro-public-info/<id>    a pro's company record (404: not a pro)
  GET  /api/onlinestores/v1/users/<id>/online_store_id   a pro's store page id (404: none)
  GET  /api/onlinestores/v1/online_stores/<id>     the store page (404: unknown)
  GET  /api/followme/v1/followers-number/<id>      followers
  GET  /api/trust-feedback/public/users/sdrn:leboncoin:user:<id>/feedback
                                                   reviews (404: unknown user, or no review yet)
  POST /api/parrot/v3/complete                     keyword suggestions
  POST /api/parrot-location/v2/complete/location   location search (204: nothing found)
  GET  /api/frontend/v1/data/v7/fdata              categories, regions, every filter
  GET  /api/frontend/v1/data/v5/fforms             which filters a category has

NOT used, because the app-style call is challenged on every try:
/finder/classified/<id> and /api/adfinder/v1/classified/<id> (one ad),
/api/same/v4/search/<id> (the site's other "similar" list),
/api/onlinestores/v2/users/<id> (the store by user). Asking for them is
also what got a test address refused on EVERY call for 40+ minutes, so
nothing here ever calls them.

Egress: one session per request thread on config.LEBONCOIN_EXIT (the
server's own IP). A challenge there holds that exit for
config.LEBONCOIN_BLOCK_COOLDOWN seconds, process-wide (one address serves
every thread, and a flagged address is refused on every call): new sessions
then ride the exits of config.LEBONCOIN_FALLBACK_EXITS in order. The first
is a gateway exit that answers from a new address on every request, about
7 in 10 of which the site lets in (29 of 40, 2026-11-20): a refusal there
is retried on the same step, a call's last retry rides the exit behind it,
and only LEBONCOIN_GATEWAY_REFUSALS refusals in a row move every session
past it. A retryable failure drops the thread's session, so the retry
rides a fresh exit.

Failure taxonomy (scraper_errors, mapped to HTTP by route_glue):
  LeboncoinUpstreamError  transport failure / 5xx / unexpected body   retryable
  LeboncoinBlocked        403 / 429 / a challenge / a non-JSON page    retryable
  LeboncoinBadRequest     the site rejected the parameters (400)       never retried
  LeboncoinNotFound       unknown ad / seller / store                  never retried
"""
import json
import threading
import time
import uuid

import config
import egress
from scraper_errors import BadRequest, Blocked, NotFound, UpstreamError
from scraper_utils import ladder, retry, sessions

API = "https://api.leboncoin.fr"
IMPERSONATE = "safari_ios"
API_TIMEOUT = 25
GATEWAY_TIMEOUT = 15            # a gateway request gets 29 s at most: fail early, retry on a new address
REFERENCE_TIMEOUT = 40          # the filter list is 0.7 MB
MAX_PAGE_SIZE = 100             # limit=200 and 500 are answered as 100
MAX_DEPTH = 3500                # rows a search goes deep: offset 3465 answers, 3500 is empty
MAX_REVIEWS_PAGE_SIZE = 300     # the site's own default; 1000 was accepted too
MAX_SIMILAR = 100               # the site's own call asks for 100

SEARCH_URL = API + "/finder/search"

# what the mobile app sends on every call (module docstring). user-agent is
# per session (it carries a device id); accept-language follows the exit.
APP_HEADERS = {"accept": "application/json"}
SEARCH_HEADERS = {**APP_HEADERS, "content-type": "application/json"}

_CHALLENGE_MARKERS = ("captcha-delivery.com", "datadome")


class LeboncoinUpstreamError(UpstreamError):
    """Transport failure, 5xx or an unexpected payload — retryable."""


class LeboncoinBlocked(LeboncoinUpstreamError, Blocked):
    """403 / 429, a DataDome challenge, or a page where JSON was expected — retryable."""


class LeboncoinBadRequest(BadRequest):
    """The site rejected the parameters (HTTP 400) — never retried."""


class LeboncoinNotFound(NotFound):
    """No such ad, seller or store — never retried."""


# ---- sessions and the exit ladder ------------------------------------------------------

# One curl session per request thread (a curl handle must not be shared
# across threads). It carries nothing expensive: a device id made up on the
# spot and whatever cookie the API hands back.
_local = threading.local()
# Process-wide: the exit step new sessions ride while a hold runs (0 = LEBONCOIN_EXIT).
_ladder_lock = threading.Lock()
_held_step = 0
_hold_until = 0.0
_gateway_refusals = 0           # refusals in a row on a gateway step


def _exits():
    """The exit ladder: the configured exit, then the fallback exits in order."""
    return [config.LEBONCOIN_EXIT, *(e for e in config.LEBONCOIN_FALLBACK_EXITS if e)]


def _is_gateway(exit):
    return bool(config.gateway_exit(exit))


def _gateway_step(step):
    """True when ladder step `step` is a gateway exit with another exit behind it."""
    exits = _exits()
    return step + 1 < len(exits) and _is_gateway(exits[step])


def _step():
    """The step a session built NOW rides: the held step while a hold runs,
    else 0; one further for the last retry of a call on a gateway step."""
    return min(ladder.current_step(_held_step, _hold_until, _local, _gateway_step), len(_exits()) - 1)


def app_user_agent():
    """The mobile app's user-agent with a device id of its own."""
    return (f"LBC;iOS;{config.LEBONCOIN_APP_OS_VERSION};iPhone;phone;{str(uuid.uuid4()).upper()};wifi;"
            f"{config.LEBONCOIN_APP_VERSION}")


def _build_session(step):
    sess = egress.exit_session(_exits()[step], impersonate=IMPERSONATE)
    sess.headers.update({"user-agent": app_user_agent(), "api_key": config.LEBONCOIN_API_KEY})
    sess._leboncoin_step = step
    return sess


def _session():
    sess = getattr(_local, "session", None)
    step = _step()
    if sess is not None and getattr(sess, "_leboncoin_step", 0) != step:
        _drop_session()                 # a session follows the ladder, in both directions
        sess = None
    if sess is None:
        sess = sessions.thread_session(_local, lambda: _build_session(step))
    return sess


def _drop_session(error=None):
    """Close the thread's session so the retry rides a fresh exit. A
    challenge also moves the ladder: off the server's own IP at once, off a
    gateway step after LEBONCOIN_GATEWAY_REFUSALS refusals in a row."""
    global _held_step, _hold_until, _gateway_refusals
    sess = getattr(_local, "session", None)
    own = getattr(sess, "_leboncoin_step", None)
    sessions.drop(_local)
    if not isinstance(error, LeboncoinBlocked) or own is None:
        return
    exits = _exits()
    with _ladder_lock:
        held = _held_step if time.time() < _hold_until else 0
        if own != held or held + 1 >= len(exits):
            return                      # a borrowed step, or the last exit: nothing behind it to move to
        if _is_gateway(exits[held]):
            _gateway_refusals += 1
            if _gateway_refusals < config.LEBONCOIN_GATEWAY_REFUSALS:
                return
        _gateway_refusals = 0
        _held_step = held + 1
        _hold_until = time.time() + config.LEBONCOIN_BLOCK_COOLDOWN
    print(f"leboncoin: exit {exits[held]!r} refused, sessions on {exits[held + 1]!r} "
          f"for {config.LEBONCOIN_BLOCK_COOLDOWN} s")


def _passed(step=None):
    """A call was let in: a gateway step's run of refusals is over. `step`
    is the step the call rode: an answer on another step (the exit behind
    the gateway, which a call's last retry borrows) says nothing about the
    gateway, so the run goes on."""
    global _gateway_refusals
    if _gateway_refusals:
        with _ladder_lock:
            if step is None or step == (_held_step if time.time() < _hold_until else 0):
                _gateway_refusals = 0


def _retrying(fn):
    """fn() under the shared retry policy: only LeboncoinUpstreamError
    (Blocked included) is retried; NotFound and BadRequest surface at once.
    The last retry of a call on a gateway step rides the exit behind it."""
    return retry.run_flagged(fn, config, LeboncoinUpstreamError, _drop_session, _local)


def reset_ladder():
    """Tests: back to the configured exit, no hold."""
    global _held_step, _hold_until, _gateway_refusals
    with _ladder_lock:
        _held_step, _hold_until, _gateway_refusals = 0, 0.0, 0


# ---- one request ---------------------------------------------------------------------

def is_challenge(status, text):
    """A DataDome answer: {"url": "https://geo.captcha-delivery.com/..."} or its HTML page."""
    head = (text or "")[:2000].lower()
    return status in (403, 429) or any(marker in head for marker in _CHALLENGE_MARKERS) and status != 200


def classify(status, text, label):
    """A 200 / 204 passes. 404 -> NotFound; 400 -> BadRequest; 403 / 429 or a
    challenge body -> Blocked; anything else -> upstream error."""
    if status in (200, 204):
        return
    if is_challenge(status, text):
        raise LeboncoinBlocked(f"HTTP {status} (challenge) for {label}")
    if status in (404, 410):
        raise LeboncoinNotFound(f"{label} not found")
    if status == 400:
        raise LeboncoinBadRequest(f"the site rejected {label}")
    if status == 401:
        raise LeboncoinBlocked(f"HTTP {status} for {label}")
    raise LeboncoinUpstreamError(f"HTTP {status} for {label}")


def decode(status, text, label, empty=None):
    """The decoded JSON of a passed answer; `empty` for a 204 or an empty body."""
    if status == 204 or not (text or "").strip():
        return empty
    try:
        return json.loads(text)
    except ValueError:
        raise LeboncoinBlocked(f"non-JSON answer for {label}: {text[:120]!r}")


def _call(method, url, label, body=None, headers=APP_HEADERS, timeout=API_TIMEOUT, empty=None):
    def once():
        sess = _session()
        if _is_gateway(_exits()[sess._leboncoin_step]):
            # every gateway request leaves from another address: a cookie the
            # site handed the address before would only tie them together
            sess.cookies.clear()
        wait = min(timeout, GATEWAY_TIMEOUT) if _is_gateway(_exits()[sess._leboncoin_step]) else timeout
        try:
            if method == "POST":
                resp = sess.post(url, data=json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
                                 headers=headers, timeout=wait)
            else:
                resp = sess.get(url, headers=headers, timeout=wait)
        except Exception as e:
            raise LeboncoinUpstreamError(f"request failed for {label}: {type(e).__name__}: {e}")
        try:
            classify(resp.status_code, resp.text, label)
        except (LeboncoinNotFound, LeboncoinBadRequest):
            _passed(sess._leboncoin_step)       # a 404 / 400 is the site's own answer: the exit was let in
            raise
        _passed(sess._leboncoin_step)
        return decode(resp.status_code, resp.text, label, empty)
    return _retrying(once)


def _object(payload, label):
    if not isinstance(payload, dict):
        raise LeboncoinUpstreamError(f"unexpected payload for {label}: {str(payload)[:120]!r}")
    return payload


# ---- ads -----------------------------------------------------------------------------

def fetch_search(body, label="search"):
    """One answer of the search call for a body queries.py built."""
    payload = _object(_call("POST", SEARCH_URL, label, body=body, headers=SEARCH_HEADERS), label)
    if "total" not in payload:
        raise LeboncoinUpstreamError(f"{label} answered no total: {str(payload)[:120]!r}")
    return payload


def fetch_similar(ad_id, limit):
    """Ads that look like this one (the site's visual match). Unknown ad -> NotFound."""
    label = f"similar ads of {ad_id}"
    url = f"{API}/api/vs-recommendation-api/v1/search/{ad_id}?limit={min(limit, MAX_SIMILAR)}"
    payload = _call("GET", url, label, empty={})
    if payload == {}:
        raise LeboncoinNotFound(f"ad {ad_id} not found")
    return _object(payload, label)


# ---- sellers -------------------------------------------------------------------------

def fetch_user_card(user_id):
    """A seller's card. Unknown user -> NotFound."""
    label = f"seller {user_id}"
    payload = _call("GET", f"{API}/api/user-card/v2/{user_id}/infos", label)
    if not isinstance(payload, dict) or not payload:
        raise LeboncoinUpstreamError(f"{label} answered no card: {str(payload)[:120]!r}")
    return payload


def _optional(method, url, label, **kw):
    """A record only some sellers have: None where the site answers 404."""
    try:
        return _call(method, url, label, **kw)
    except LeboncoinNotFound:
        return None


def fetch_pro_info(user_id):
    """A pro seller's company record (SIREN, SIRET, address); None for a private seller."""
    return _optional("GET", f"{API}/api/users/v1/users/pro-public-info/{user_id}", f"company record of {user_id}")


def fetch_store_id(user_id):
    """The id of a pro seller's store page; None when the seller has none."""
    payload = _optional("GET", f"{API}/api/onlinestores/v1/users/{user_id}/online_store_id", f"store id of {user_id}")
    found = (payload or {}).get("online_store_id") if isinstance(payload, dict) else None
    return found or None


def fetch_store(store_id):
    """A store page in full. Unknown store -> NotFound."""
    label = f"store {store_id}"
    payload = _call("GET", f"{API}/api/onlinestores/v1/online_stores/{store_id}", label)
    if not isinstance(payload, dict) or not payload.get("online_store_id"):
        raise LeboncoinNotFound(f"{label} not found")
    return payload


def fetch_followers(user_id):
    """How many members follow a seller (0 for an unknown one)."""
    payload = _optional("GET", f"{API}/api/followme/v1/followers-number/{user_id}", f"followers of {user_id}")
    return payload if isinstance(payload, dict) else {}


def fetch_reviews(user_id, page, limit):
    """One page of the reviews a seller received, with the score summary
    (page is 1-based here, 0-based upstream). None when the site knows no
    review of that user: it answers 404 for a user without reviews and for
    an unknown user alike."""
    url = (f"{API}/api/trust-feedback/public/users/sdrn:leboncoin:user:{user_id}/feedback"
           f"?limit={min(limit, MAX_REVIEWS_PAGE_SIZE)}&page={max(page - 1, 0)}")
    return _optional("GET", url, f"reviews of {user_id}")


# ---- suggestions, locations, reference data --------------------------------------------

def fetch_suggestions(keyword):
    label = f"suggestions {keyword!r}"
    return _object(_call("POST", f"{API}/api/parrot/v3/complete", label, body={"keyword": keyword},
                         headers=SEARCH_HEADERS, empty={}), label)


def fetch_locations(text):
    """The site's location search: a list of location objects, [] when it finds none (HTTP 204)."""
    label = f"locations {text!r}"
    payload = _call("POST", f"{API}/api/parrot-location/v2/complete/location", label, body={"text": text},
                    headers=SEARCH_HEADERS, empty=[])
    if not isinstance(payload, list):
        raise LeboncoinUpstreamError(f"unexpected payload for {label}: {str(payload)[:120]!r}")
    return payload


def fetch_reference():
    """(fdata, fforms): the categories, regions and every filter with its
    values; and which filters each category has."""
    fdata = _object(_call("GET", f"{API}/api/frontend/v1/data/v7/fdata", "reference data", timeout=REFERENCE_TIMEOUT),
                    "reference data")
    if not isinstance(fdata.get("categories"), list) or not isinstance(fdata.get("features"), dict):
        raise LeboncoinUpstreamError("reference data answered no categories")
    fforms = _object(_call("GET", f"{API}/api/frontend/v1/data/v5/fforms", "filter forms", timeout=REFERENCE_TIMEOUT),
                     "filter forms")
    return fdata, fforms
