"""Offline tests for the transport's reading of the site's answers and its
exit ladder (leboncoin/fetch.py) and for the endpoint logic
(leboncoin/api.py), with the network and the cache replaced by fakes (the
answers are the fixtures).

    python -m pytest leboncoin/test_api.py -q
"""
import gzip
import json
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config  # noqa: E402
from leboncoin import api, fetch, parsers  # noqa: E402
from scraper_errors import BadRequest, Blocked, NotFound, UpstreamError  # noqa: E402
from scraper_utils.testing import hosted_only  # noqa: E402

FX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
PRO = "031c778f-f4bd-4969-98a8-179c1f4efd2f"
RATED = "148417de-bb7d-4cd2-87c9-7dfb5ccff35e"


def raw(name):
    opener = gzip.open if name.endswith(".gz") else open
    with opener(os.path.join(FX, name), "rt", encoding="utf-8") as f:
        return f.read()


def fixture(name):
    return json.loads(raw(name))


# ---- the transport: reading an answer --------------------------------------------------

def test_error_classes_follow_the_shared_taxonomy():
    assert issubclass(fetch.LeboncoinBlocked, Blocked) and issubclass(fetch.LeboncoinBlocked, fetch.LeboncoinUpstreamError)
    assert issubclass(fetch.LeboncoinUpstreamError, UpstreamError)
    assert issubclass(fetch.LeboncoinBadRequest, BadRequest) and issubclass(fetch.LeboncoinNotFound, NotFound)
    assert not issubclass(fetch.LeboncoinNotFound, UpstreamError)


@pytest.mark.parametrize("status, body, kind", [
    (403, raw("blocked_captcha.json"), fetch.LeboncoinBlocked),       # DataDome's JSON answer
    (403, raw("blocked_page.html"), fetch.LeboncoinBlocked),          # and its HTML form
    (429, "", fetch.LeboncoinBlocked),
    (401, "", fetch.LeboncoinBlocked),
    (404, "", fetch.LeboncoinNotFound),                               # seller / store / similar: an empty 404
    (404, raw("reviews_not_found.json"), fetch.LeboncoinNotFound),
    (410, "", fetch.LeboncoinNotFound),
    (400, "", fetch.LeboncoinBadRequest),                             # an unknown sort: 400, empty body
    (500, "oops", fetch.LeboncoinUpstreamError),
    (502, raw("blocked_page.html"), fetch.LeboncoinBlocked),          # a challenge page under another status
])
def test_classify(status, body, kind):
    with pytest.raises(kind) as error:
        fetch.classify(status, body, "thing")
    assert type(error.value) is kind


def test_classify_passes_a_real_answer():
    assert fetch.classify(200, raw("search_no_result.json"), "search") is None
    assert fetch.classify(204, "", "locations") is None
    # an ad whose text names the protection is still an answer
    assert fetch.classify(200, '{"ads": [{"body": "datadome captcha-delivery.com"}]}', "search") is None


def test_decode():
    assert fetch.decode(200, '{"a": 1}', "x") == {"a": 1}
    assert fetch.decode(204, "", "x", empty=[]) == [] and fetch.decode(200, "  ", "x", empty={}) == {}
    with pytest.raises(fetch.LeboncoinBlocked):
        fetch.decode(200, "<html>not json</html>", "x")


def test_app_user_agent_and_headers():
    agent = fetch.app_user_agent()
    parts = agent.split(";")
    assert parts[:5] == ["LBC", "iOS", config.LEBONCOIN_APP_OS_VERSION, "iPhone", "phone"]
    assert parts[6:] == ["wifi", config.LEBONCOIN_APP_VERSION] and len(parts[5]) == 36 and parts[5] == parts[5].upper()
    assert fetch.app_user_agent() != agent                        # a device id of its own each time
    # the app sends no web headers: with the page's origin / referer the call is refused
    for headers in (fetch.APP_HEADERS, fetch.SEARCH_HEADERS):
        assert headers["accept"] == "application/json"
        assert not {"origin", "referer", "accept-language", "user-agent"} & set(headers)
    assert fetch.IMPERSONATE == "safari_ios"


# ---- the transport: one call ---------------------------------------------------------

class Answer:
    def __init__(self, status=200, body=""):
        self.status_code = status
        self.text = body if isinstance(body, str) else json.dumps(body)
        self.content = self.text.encode()


class Jar:
    def __init__(self):
        self.cleared = 0

    def clear(self):
        self.cleared += 1


class Wire:
    """A session whose answers are queued; it records what was sent."""

    def __init__(self, monkeypatch, *answers, step=0):
        self.answers = list(answers)
        self.sent = []
        self.dropped = []
        self.cookies = Jar()
        self._leboncoin_step = step
        monkeypatch.setattr(fetch, "_session", lambda: self)
        monkeypatch.setattr(fetch, "_drop_session", self.dropped.append)
        monkeypatch.setattr(fetch.retry.time, "sleep", lambda seconds: None)

    def _next(self, method, url, headers, data, timeout):
        self.sent.append({"method": method, "url": url, "headers": headers, "body": data, "timeout": timeout})
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    def post(self, url, data=None, headers=None, timeout=None):
        return self._next("POST", url, headers, data, timeout)

    def get(self, url, headers=None, timeout=None):
        return self._next("GET", url, headers, None, timeout)


def test_search_is_sent_as_the_app_sends_it(monkeypatch):
    wire = Wire(monkeypatch, Answer(body=fixture("search_no_result.json")))
    body = {"filters": {"keywords": {"text": "vélo"}}, "limit": 35}
    assert fetch.fetch_search(body)["total"] == 0
    sent = wire.sent[0]
    assert sent["method"] == "POST" and sent["url"] == "https://api.leboncoin.fr/finder/search"
    assert sent["headers"] == {"accept": "application/json", "content-type": "application/json"}
    assert json.loads(sent["body"].decode("utf-8")) == body and "vélo".encode("utf-8") in sent["body"]
    assert wire.cookies.cleared == 0 and sent["timeout"] == fetch.API_TIMEOUT


def test_a_challenge_is_retried_on_a_fresh_session_then_given_up(monkeypatch):
    wire = Wire(monkeypatch, *[Answer(403, raw("blocked_captcha.json"))] * config.MAX_RETRIES)
    with pytest.raises(fetch.LeboncoinBlocked):
        fetch.fetch_search({"filters": {}})
    assert len(wire.sent) == config.MAX_RETRIES and len(wire.dropped) == config.MAX_RETRIES
    assert all(isinstance(e, fetch.LeboncoinBlocked) for e in wire.dropped)


def test_a_retry_that_passes_answers(monkeypatch):
    wire = Wire(monkeypatch, Answer(403, raw("blocked_captcha.json")), ConnectionError("cut"),
                Answer(body=fixture("search_no_result.json")))
    assert fetch.fetch_search({"filters": {}})["total"] == 0
    assert len(wire.sent) == 3 and len(wire.dropped) == 2


def test_not_found_and_bad_request_are_final(monkeypatch):
    wire = Wire(monkeypatch, Answer(404, ""))
    with pytest.raises(fetch.LeboncoinNotFound):
        fetch.fetch_user_card(PRO)
    assert len(wire.sent) == 1 and wire.dropped == []
    wire = Wire(monkeypatch, Answer(400, ""))
    with pytest.raises(fetch.LeboncoinBadRequest):
        fetch.fetch_search({"sort_by": "nonsense"})
    assert len(wire.sent) == 1


def test_records_only_some_sellers_have_answer_none(monkeypatch):
    Wire(monkeypatch, Answer(404, ""), Answer(404, ""), Answer(404, raw("reviews_not_found.json")),
         Answer(body={"online_store_id": 338302, "account_id": 0}))
    assert fetch.fetch_pro_info(PRO) is None and fetch.fetch_store_id(PRO) is None
    assert fetch.fetch_reviews(PRO, 1, 20) is None
    assert fetch.fetch_store_id(PRO) == 338302


def test_urls_of_the_get_calls(monkeypatch):
    wire = Wire(monkeypatch, Answer(body=fixture("reviews_page_1.json")), Answer(body=fixture("similar_ads.json")),
                Answer(body=fixture("store_338302.json")), Answer(204, ""), Answer(404, ""))
    fetch.fetch_reviews(RATED, 3, 500)
    fetch.fetch_similar("3091399005", 500)
    fetch.fetch_store(338302)
    assert fetch.fetch_locations("zzqx") == []                    # the site answers 204 when it finds nothing
    with pytest.raises(fetch.LeboncoinNotFound):
        fetch.fetch_similar("9999999999", 10)
    urls = [s["url"] for s in wire.sent]
    assert urls[0] == (f"https://api.leboncoin.fr/api/trust-feedback/public/users/sdrn:leboncoin:user:{RATED}"
                       "/feedback?limit=300&page=2")                # 1-based here, 0-based upstream; capped
    assert urls[1] == "https://api.leboncoin.fr/api/vs-recommendation-api/v1/search/3091399005?limit=100"
    assert urls[2] == "https://api.leboncoin.fr/api/onlinestores/v1/online_stores/338302"
    assert all(s["headers"]["accept"] == "application/json" for s in wire.sent)
    # the endpoints DataDome challenges for the app are never asked
    assert not any("/classified/" in u or "/same/" in u or "/onlinestores/v2/" in u for u in urls)


@hosted_only
def test_a_gateway_request_carries_no_cookie_and_a_short_timeout(monkeypatch):
    monkeypatch.setattr(config, "LEBONCOIN_FALLBACK_EXITS", ("gateway:fr", "fr"))
    wire = Wire(monkeypatch, Answer(body=fixture("search_no_result.json")), step=1)
    fetch.fetch_search({"filters": {}})
    assert wire.cookies.cleared == 1 and wire.sent[0]["timeout"] == fetch.GATEWAY_TIMEOUT


@hosted_only
def test_what_ends_a_gateways_run_of_refusals(monkeypatch):
    monkeypatch.setattr(config, "LEBONCOIN_FALLBACK_EXITS", ("gateway:fr", "fr"))
    monkeypatch.setattr(fetch, "_held_step", 1)                   # sessions on the gateway, two refusals so far
    monkeypatch.setattr(fetch, "_hold_until", time.time() + 600)
    monkeypatch.setattr(fetch, "_gateway_refusals", 2)
    Wire(monkeypatch, Answer(body=fixture("search_no_result.json")), step=2)
    fetch.fetch_search({"filters": {}})                           # a call's last retry, on the exit behind the gateway
    assert fetch._gateway_refusals == 2                           # says nothing about the gateway: the run goes on
    Wire(monkeypatch, Answer(404, ""), step=1)
    with pytest.raises(fetch.LeboncoinNotFound):
        fetch.fetch_user_card(PRO)
    assert fetch._gateway_refusals == 0                           # a 404 is the site's own answer: the gateway let it in


# ---- the transport: the exit ladder ----------------------------------------------------

class Sess:
    def __init__(self, exit):
        self.exit = exit
        self.headers = {}
        self.closed = False

    def close(self):
        self.closed = True


@pytest.fixture
def ladder(monkeypatch):
    built = []

    def exit_session(exit, impersonate="chrome"):
        sess = Sess(exit)
        sess.impersonate = impersonate
        built.append(sess)
        return sess
    monkeypatch.setattr(fetch.egress, "exit_session", exit_session)
    monkeypatch.setattr(config, "LEBONCOIN_EXIT", "direct")
    monkeypatch.setattr(config, "LEBONCOIN_FALLBACK_EXITS", ("gateway:fr", "fr"))
    monkeypatch.setattr(config, "LEBONCOIN_GATEWAY_REFUSALS", 3)
    fetch.reset_ladder()
    fetch._local.session = None
    fetch._local.past_gateway = False
    yield built
    fetch.reset_ladder()
    fetch._local.session = None
    fetch._local.past_gateway = False


@hosted_only
def test_a_session_starts_on_the_configured_exit_as_the_app(ladder):
    sess = fetch._session()
    assert sess.exit == "direct" and sess.impersonate == "safari_ios"
    assert sess.headers["user-agent"].startswith("LBC;iOS;") and sess.headers["api_key"] == config.LEBONCOIN_API_KEY
    assert fetch._session() is sess and len(ladder) == 1          # one per thread, kept


@hosted_only
def test_a_challenge_on_the_own_ip_moves_every_session_to_the_gateway(ladder):
    first = fetch._session()
    fetch._drop_session(fetch.LeboncoinBlocked("403"))
    assert first.closed and fetch._session().exit == "gateway:fr"
    assert fetch._hold_until > 0


@hosted_only
def test_a_transport_error_moves_nothing(ladder):
    fetch._session()
    fetch._drop_session(fetch.LeboncoinUpstreamError("timeout"))
    fetch._drop_session(None)
    assert fetch._session().exit == "direct"


@hosted_only
def test_the_gateway_is_left_only_after_refusals_in_a_row(ladder):
    fetch._session()
    fetch._drop_session(fetch.LeboncoinBlocked("403"))            # direct -> gateway
    for _ in range(2):
        assert fetch._session().exit == "gateway:fr"
        fetch._drop_session(fetch.LeboncoinBlocked("403"))
    assert fetch._session().exit == "gateway:fr"                  # two refusals: about 3 in 10 are refused anyway
    fetch._passed()                                               # a call got through: the run is over
    for _ in range(2):
        fetch._drop_session(fetch.LeboncoinBlocked("403"))
        assert fetch._session().exit == "gateway:fr"
    fetch._drop_session(fetch.LeboncoinBlocked("403"))            # the third in a row
    assert fetch._session().exit == "fr"
    fetch._drop_session(fetch.LeboncoinBlocked("403"))            # the last exit: nowhere further to go
    assert fetch._session().exit == "fr"


@hosted_only
def test_an_answer_on_the_exit_behind_the_gateway_does_not_end_its_run(ladder):
    fetch._session()
    fetch._drop_session(fetch.LeboncoinBlocked("403"))            # direct -> gateway
    for _ in range(3):                                            # three calls, each refused once on the gateway
        assert fetch._session().exit == "gateway:fr"
        fetch._drop_session(fetch.LeboncoinBlocked("403"))
        fetch._passed(2)                                          # ... and answered by its last retry, on the exit behind
    assert fetch._session().exit == "fr"                          # three refusals in a row: the gateway is left


@hosted_only
def test_a_calls_last_retry_on_the_gateway_rides_the_exit_behind_it(ladder):
    fetch._session()
    fetch._drop_session(fetch.LeboncoinBlocked("403"))            # sessions on the gateway
    fetch._local.past_gateway = True                              # what retry.run_flagged sets for the last attempt
    borrowed = fetch._session()
    assert borrowed.exit == "fr"
    fetch._drop_session(fetch.LeboncoinBlocked("403"))            # a refusal of the borrowed exit moves nothing
    fetch._local.past_gateway = False
    assert fetch._session().exit == "gateway:fr"


@hosted_only
def test_sessions_return_to_the_own_ip_after_the_hold(ladder, monkeypatch):
    fetch._session()
    fetch._drop_session(fetch.LeboncoinBlocked("403"))
    on_gateway = fetch._session()
    assert on_gateway.exit == "gateway:fr"
    monkeypatch.setattr(fetch, "_hold_until", 1.0)                # the hold ran out
    assert fetch._session().exit == "direct" and on_gateway.closed


@hosted_only
def test_no_fallback_exits_means_no_ladder(ladder, monkeypatch):
    monkeypatch.setattr(config, "LEBONCOIN_FALLBACK_EXITS", ())
    fetch._session()
    fetch._drop_session(fetch.LeboncoinBlocked("403"))
    assert fetch._session().exit == "direct"


# ---- the endpoints -------------------------------------------------------------------

class Site:
    """api.py's upstream calls answered from the fixtures; cached_call in memory."""

    def __init__(self, monkeypatch):
        self.calls = []
        self.bodies = []
        self.rows = {}
        self.search_answer = fixture("search_iphone_15.json")
        self.cards = {PRO: fixture("seller_pro.json"), RATED: fixture("seller_private_rated.json")}
        self.reviews = {RATED: fixture("reviews_page_1.json")}
        self.places = {"lyon": fixture("locations_lyon.json")}
        for name in ("fetch_search", "fetch_similar", "fetch_user_card", "fetch_pro_info", "fetch_store_id",
                     "fetch_store", "fetch_followers", "fetch_reviews", "fetch_suggestions", "fetch_locations",
                     "fetch_reference"):
            monkeypatch.setattr(api, name, getattr(self, name))
        monkeypatch.setattr(api, "cached_call", self.cache)
        monkeypatch.setattr(api, "_reference_store", {})

    def cache(self, namespace, data, fn, ttl):
        key = (namespace, json.dumps(data, sort_keys=True, default=str))
        if key not in self.rows:
            self.rows[key] = fn(**data)
        return self.rows[key]

    def fetch_search(self, body, label="search"):
        self.calls.append("search")
        self.bodies.append(body)
        if "pivot" in body:
            return fixture("ads_by_id.json")
        return self.search_answer

    def fetch_similar(self, ad_id, limit):
        self.calls.append("similar")
        return fixture("similar_ads.json")

    def fetch_user_card(self, user_id):
        self.calls.append("card")
        if user_id not in self.cards:
            raise fetch.LeboncoinNotFound(f"seller {user_id} not found")
        return self.cards[user_id]

    def fetch_pro_info(self, user_id):
        self.calls.append("company")
        return fixture("seller_pro_company.json")

    def fetch_store_id(self, user_id):
        self.calls.append("store_id")
        return 338302

    def fetch_store(self, store_id):
        self.calls.append("store")
        if int(store_id) != 338302:
            raise fetch.LeboncoinNotFound("no store")
        return fixture("store_338302.json")

    def fetch_followers(self, user_id):
        self.calls.append("followers")
        return fixture("followers.json")

    def fetch_reviews(self, user_id, page, limit):
        self.calls.append("reviews")
        return self.reviews.get(user_id)

    def fetch_suggestions(self, keyword):
        self.calls.append("suggestions")
        return fixture("suggestions_iphone.json")

    def fetch_locations(self, text):
        self.calls.append("locations")
        return self.places.get(text.casefold(), [])

    def fetch_reference(self):
        self.calls.append("reference")
        return fixture("fdata.json.gz"), fixture("fforms.json")


@pytest.fixture
def site(monkeypatch):
    return Site(monkeypatch)


def search(**given):
    base = {"query": None, "category": None, "location": None, "radius": None, "price_min": None, "price_max": None,
            "seller_type": None, "ad_type": None, "sort": None, "title_only": None, "include_delivery": None,
            "urgent_only": None, "free_only": None, "filters": None, "page": 1, "limit": 35}
    return api.ads_search(**{**base, **given})


def test_keyword_search(site):
    out = search(query={"text": "iphone 15"}, limit=5)
    assert site.bodies[0] == {"filters": {"enums": {"ad_type": ["offer"]}, "keywords": {"text": "iphone 15"}},
                              "sort_by": "relevance", "limit": 5}
    assert list(out)[:8] == ["query", "category", "locations", "radius_km", "seller_type", "ad_type", "sort", "filters"]
    assert out["query"] == "iphone 15" and out["category"] is None and out["sort"] == "relevance" and out["ad_type"] == "offer"
    assert len(out["ads"]) == 5 and out["pagination"]["total_count"] == 34845
    assert site.calls == ["search"]                                # no reference data needed for a plain search


def test_search_with_every_kind_of_filter(site):
    out = search(query={"text": "208"}, category="voitures", location=[{"text": "Lyon"}, {"locationType": "department", "department_id": "69"}],
                 radius=30, price_min=5000, price_max=15000, seller_type="pro", sort="price_asc", title_only=True,
                 include_delivery=True, urgent_only=True, filters=[["fuel", "essence"], ["mileage", "min-100000"]], page=2)
    body = site.bodies[0]
    assert body["filters"]["category"] == {"id": "2"}
    assert body["filters"]["keywords"] == {"text": "208", "type": "subject"}
    assert body["filters"]["enums"] == {"ad_type": ["offer"], "fuel": ["1"], "urgent": ["1"]}
    assert body["filters"]["ranges"] == {"mileage": {"max": 100000}, "price": {"min": 5000, "max": 15000}}
    lyon, rhone = body["filters"]["location"]["locations"]
    assert lyon["city"] == "Lyon" and lyon["area"]["radius"] == 30000 and rhone == {"locationType": "department", "department_id": "69"}
    assert body["filters"]["location"]["shippable"] is True
    assert (body["sort_by"], body["sort_order"], body["owner_type"], body["offset"]) == ("price", "asc", "pro", 35)
    assert out["category"] == {"id": "2", "name": "Voitures", "slug": "voitures"}
    assert out["locations"] == ["Lyon (toute la ville)", "d_69"] and out["radius_km"] == 30
    assert {"key": "fuel", "value": "1"} in out["filters"] and {"key": "mileage", "value": "min-100000"} in out["filters"]


def test_a_search_link_is_followed_and_explicit_params_win(site):
    link = {"category": "2", "seller_type": "pro", "sort": "newest", "page": 9, "query": "clio",
            "filters": [["u_car_brand", "PEUGEOT"], ["fuel", "1|2"]]}
    search(query={"link": link}, sort="price_desc", filters=[["fuel", "2"]])
    body = site.bodies[0]
    assert body["filters"]["category"] == {"id": "2"} and body["filters"]["keywords"] == {"text": "clio"}
    assert body["filters"]["enums"] == {"ad_type": ["offer"], "u_car_brand": ["PEUGEOT"], "fuel": ["2"]}
    assert body["owner_type"] == "pro" and (body["sort_by"], body["sort_order"]) == ("price", "desc")
    assert "offset" not in body                                    # `page` pages; the link's own page is not used


def test_a_price_bound_given_keeps_the_links_other_bound(site):
    link = {"filters": [["price", "min-100"]]}
    search(query={"link": link}, price_min=20)
    assert site.bodies[0]["filters"]["ranges"] == {"price": {"min": 20, "max": 100}}
    search(query={"link": link}, price_min=200)                    # above the link's highest price: the param alone wins
    assert site.bodies[1]["filters"]["ranges"] == {"price": {"min": 200}}
    search(query={"link": link}, price_min=20, price_max=50)
    assert site.bodies[2]["filters"]["ranges"] == {"price": {"min": 20, "max": 50}}


def test_a_slug_finds_its_own_category_not_the_group_of_the_same_name(site):
    # /c/animaux is category 28; its group "Animaux" (75, slug _animaux_) has the same name
    assert search(category="animaux")["category"] == {"id": "28", "name": "Animaux", "slug": "animaux"}
    assert site.bodies[0]["filters"]["category"] == {"id": "28"}
    assert search(category="_animaux_")["category"]["id"] == "75"


def test_a_mirror_category_is_searched_as_the_site_searches_it(site):
    out = search(category="immobilier_neuf")
    body = site.bodies[0]
    # the site answers category 2001 itself with every ad there is: its target and filter are sent
    assert body["filters"]["category"] == {"id": "9"} and body["filters"]["enums"]["immo_sell_type"] == ["new"]
    assert out["category"]["id"] == "2001"
    search(category="dons")
    assert "category" not in site.bodies[1]["filters"] and site.bodies[1]["filters"]["enums"]["donation"] == ["1"]


@pytest.mark.parametrize("given, fragment", [
    ({"category": "300"}, "not searched on leboncoin"),
    ({"filters": [["nope", "1"]]}, "no filter named 'nope'"),
    ({"filters": [["fuel", "99"]]}, "has no value '99'"),
    ({"price_min": 500, "price_max": 100}, "price_min is above price_max"),
    ({"location": [{"locationType": "department", "department_id": "69"}], "radius": 10}, "radius needs a city"),
    ({"query": {"link": {"seller_type": "shop"}}}, "seller_type"),
])
def test_what_the_site_would_silently_ignore_is_a_400(site, given, fragment):
    with pytest.raises(ValueError) as error:
        search(**given)
    assert fragment in str(error.value)
    assert "search" not in site.calls


@pytest.mark.parametrize("given, fragment", [
    ({"category": "nope"}, "category 'nope' not found"),
    ({"location": [{"text": "zzqx"}]}, "location 'zzqx' not found"),
])
def test_an_unknown_category_or_place_is_a_404(site, given, fragment):
    with pytest.raises(fetch.LeboncoinNotFound) as error:
        search(**given)
    assert fragment in str(error.value) and "search" not in site.calls
    with pytest.raises(fetch.LeboncoinNotFound):
        api.categories_filters(category="nope", filters=None)


def test_ad_details_and_not_found(site):
    assert api.ads_details(ad="3285245707")["id"] == 3285245707
    assert json.loads(site.bodies[0]["pivot"]) == {"ids_to_display": ["3285245707"]}
    with pytest.raises(fetch.LeboncoinNotFound) as error:
        api.ads_details(ad="9999999999")
    assert "ad 9999999999 not found" in str(error.value)


def test_bulk_names_what_was_not_found(site):
    out = api.ads_bulk(ads=["3277956465", "9999999999", "3285245707"])
    assert (out["requested_count"], out["found_count"], out["not_found"]) == (3, 2, [9999999999])
    assert [ad["id"] for ad in out["ads"]] == [3277956465, 3285245707]
    assert site.calls == ["search"]                                # one upstream call for the batch


def test_similar(site):
    out = api.ads_similar(ad="3091399005", limit=2)
    assert out["ad_id"] == 3091399005 and out["count"] == 2 and len(out["ads"]) == 2


def test_pro_seller_reads_card_company_store_and_followers(site):
    out = api.sellers_details(seller=PRO)
    assert out["type"] == "pro" and out["website"] == "http://simsize.fr/" and out["followers_count"] == 57
    assert out["company"]["siret"] == "79120876200017" and out["store"]["id"] == 338302
    assert site.calls == ["card", "company", "store_id", "store", "followers"]


def test_private_seller_costs_two_calls(site):
    out = api.sellers_details(seller=RATED)
    assert out["type"] == "private" and out["company"] is None and out["store"] is None and out["website"] is None
    assert site.calls == ["card", "followers"]


def test_a_store_link_finds_its_owner(site):
    out = api.sellers_details(seller="boutique:338302")
    assert out["id"] == PRO and out["store"]["id"] == 338302
    assert site.calls == ["store", "card", "company", "followers"]        # the store page is not fetched twice
    with pytest.raises(fetch.LeboncoinNotFound) as error:
        api.sellers_details(seller="boutique:1")
    assert "store 1 not found" in str(error.value)


def test_unknown_seller_is_not_found(site):
    with pytest.raises(fetch.LeboncoinNotFound):
        api.sellers_details(seller="00000000-0000-4000-8000-000000000000")


def test_seller_ads(site):
    out = api.sellers_ads(seller=PRO, page=1, limit=35)
    body = site.bodies[0]
    assert body["filters"]["owner"] == {"user_id": PRO} and (body["sort_by"], body["sort_order"]) == ("time", "desc")
    assert out["seller_id"] == PRO and out["seller_link"].endswith(f"/profile/{PRO}/offers") and len(out["ads"]) == 5
    assert list(out) == ["seller_id", "seller_link", "ads", "pagination"]


def test_seller_ads_tells_no_ads_from_no_seller(site):
    site.search_answer = fixture("search_no_result.json")
    out = api.sellers_ads(seller=PRO, page=1, limit=35)
    assert out["ads"] == [] and out["pagination"]["total_count"] == 0 and site.calls == ["search", "card"]
    with pytest.raises(fetch.LeboncoinNotFound):
        api.sellers_ads(seller="00000000-0000-4000-8000-000000000000", page=1, limit=35)


def test_seller_reviews(site):
    out = api.sellers_reviews(seller=RATED, page=1, limit=5)
    assert out["summary"]["reviews_count"] == 48 and len(out["reviews"]) == 5
    assert out["pagination"] == {"page": 1, "items_per_page": 5, "total_count": 48, "total_pages": 10}
    assert site.calls == ["reviews"]


def test_reviews_tell_no_review_from_no_seller(site):
    # the review service answers 404 for both: the seller card settles it
    out = api.sellers_reviews(seller=PRO, page=1, limit=20)
    assert out["reviews"] == [] and out["summary"]["reviews_count"] == 0 and out["pagination"]["total_count"] == 0
    with pytest.raises(fetch.LeboncoinNotFound):
        api.sellers_reviews(seller="00000000-0000-4000-8000-000000000000", page=1, limit=20)


def test_suggestions_and_locations(site):
    out = api.search_suggestions(query="iphone 15")
    assert out["count"] == 5 and out["suggestions"][0]["category"]["name"] == "Téléphones & Objets connectés"
    places = api.locations_search(query="lyon")
    assert places["count"] == 9 and places["locations"][0]["value"].startswith("Lyon__45.76")
    assert api.locations_search(query="zzqx") == {"query": "zzqx", "count": 0, "locations": []}


def test_suggestions_survive_a_reference_failure(site, monkeypatch):
    def broken():
        raise fetch.LeboncoinBlocked("403")
    monkeypatch.setattr(api, "fetch_reference", broken)
    out = api.search_suggestions(query="iphone 15")
    assert out["suggestions"][0]["category"] == {"id": "17", "name": None, "slug": None}


def test_categories_and_filters(site):
    listing = api.categories_list()
    assert listing["count"] == 114 and listing["categories"][0]["subcategories"]
    out = api.categories_filters(category="voitures", filters=None)
    assert out["category"] == {"id": "2", "name": "Voitures", "slug": "voitures"} and out["count"] == 19
    opened = api.categories_filters(category="2", filters=[["u_car_brand", "peugeot"]])
    models = next(f for f in opened["filters"] if f["key"] == "u_car_model")
    assert len(models["values"]) == 55
    # a mirror category has the filters of the category it mirrors
    assert api.categories_filters(category="2001", filters=None)["count"] == api.categories_filters(category="9", filters=None)["count"]
    with pytest.raises(ValueError):
        api.categories_filters(category="2", filters=[["nope", "1"]])
    assert site.calls.count("reference") == 1                      # parsed once for all of it


def test_parsers_are_what_the_endpoints_return(site):
    out = api.ads_details(ad="3285245707")
    assert out == parsers.parse_bulk(fixture("ads_by_id.json"), ["3285245707"])["ads"][0]
