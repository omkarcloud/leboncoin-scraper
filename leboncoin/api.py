"""The /leboncoin/* endpoint functions (route_glue's route_table calls them
with the schema's loaded kwargs).

Caching (cache.cached_call) sits here, on the answers and on the pieces
several endpoints read:

  leboncoin.search      a search page
  leboncoin.details     one ad;  leboncoin.bulk  a batch of them
  leboncoin.place       a place name the site's own location search placed
                        (ads/search resolves `location=Lyon` through it)
  leboncoin.store       a store page asked by its id, to find its owner
                        (sellers/ads and sellers/reviews take a store link)
  the reference data    categories and filters, parsed once per process
                        (cache_config.REFERENCE_SECONDS)

  leboncoin.seller      sellers/details (the route's website-contacts
                        wrapper is given no TTL: the answer is cached here)

Every ad endpoint but ads/similar rides one upstream call, POST
/finder/search (fetch.py): a search, a seller's ads, and ads by id.
"""
import threading

from cache import cached_call
from leboncoin import cache_config as ttl
from leboncoin import parsers, queries, refs
from leboncoin.fetch import (LeboncoinNotFound, LeboncoinUpstreamError, fetch_followers, fetch_locations,
                             fetch_pro_info, fetch_reference, fetch_reviews, fetch_search, fetch_similar,
                             fetch_store, fetch_store_id, fetch_suggestions, fetch_user_card)
from scraper_utils import memo

_SORT_DEFAULT = "relevance"
_CATEGORY_KEYS = ("id", "name", "slug")

_reference_store = {}
_reference_lock = threading.Lock()


# ---- reference data (shared) -----------------------------------------------------------

def _build_reference():
    return parsers.parse_reference(*fetch_reference())


def reference():
    """The site's categories and filters, parsed (one fetch per process a day)."""
    return memo.expiring(_reference_store, _reference_lock, "reference", ttl.REFERENCE_SECONDS, _build_reference)


def _category(value):
    """`category` as given (an id, a slug or a name) -> its record. An
    unknown one is NotFound (the site would silently search every category
    instead); one the site only links out to is a ValueError."""
    ref = reference()
    record = ref["by_id"].get(value) or ref["by_id"].get(ref["by_slug"].get(str(value).casefold()))
    if record is None:
        raise LeboncoinNotFound(f"category '{value}' not found. /leboncoin/categories/list lists them.")
    if record["external_link"]:
        raise ValueError(f"category: '{record['name']}' is not searched on leboncoin (it links to {record['external_link']}).")
    return record


def _searched_category(record):
    """(category id for the call, the enums a mirror category adds). The
    site answers a mirror category's own id with every ad there is, so its
    target category and filters are sent instead."""
    same = record["same_as"]
    if not same:
        return record["id"], {}
    target = same["category_id"] if same["category_id"] not in (None, "0") else None
    return target, {f["key"]: f["value"].split("|") for f in same["filters"]}


# ---- locations (shared) ----------------------------------------------------------------

def _fetch_place(text):
    rows = fetch_locations(text)
    return rows[0] if rows and isinstance(rows[0], dict) else None


def _place(text):
    """A place name -> the site's first location for it (cached)."""
    found = cached_call("leboncoin.place", {"text": text.casefold()}, _fetch_place, ttl.LOCATIONS_CACHE)
    if not found:
        raise LeboncoinNotFound(f"location '{text}' not found. /leboncoin/locations/search finds the places leboncoin knows.")
    return found


def _locations(given):
    return [_place(loc["text"]) if "text" in loc else loc for loc in given or []]


def _location_labels(locations):
    return [loc.get("label") or refs.location_token(loc) for loc in locations]


# ---- ads/search ------------------------------------------------------------------------

def _merged(data):
    """The caller's params over the ones a search link in `query` carries
    (the link's page is not used: `page` pages through its results)."""
    query = data.get("query") or {}
    link = query.get("link") or {}
    merged = {
        "text": query.get("text") or link.get("query"),
        "category": data.get("category") or link.get("category"),
        "location": data.get("location") or link.get("location"),
        "seller_type": data.get("seller_type") or link.get("seller_type"),
        "ad_type": data.get("ad_type") or link.get("ad_type"),
        "sort": data.get("sort") or link.get("sort") or _SORT_DEFAULT,
        "title_only": data["title_only"] if data.get("title_only") is not None else bool(link.get("title_only")),
        "include_delivery": (data["include_delivery"] if data.get("include_delivery") is not None
                             else bool(link.get("include_delivery"))),
    }
    filters = {key: value for key, value in link.get("filters") or []}
    filters.update({key: value for key, value in data.get("filters") or []})
    if data.get("urgent_only"):
        filters["urgent"] = "1"
    if data.get("free_only"):
        filters["donation"] = "1"
    merged["filters"] = [[key, value] for key, value in filters.items()]
    for name, table in (("seller_type", refs.SELLER_TYPES), ("ad_type", refs.AD_TYPES)):
        if merged[name] and merged[name] not in table.values():
            raise ValueError(f"query: the link asks for a {name} this API does not know: '{merged[name]}'.")
    return merged


def _ads_search(**data):
    asked = _merged(data)
    page, limit = data["page"], data["limit"]
    category = _category(asked["category"]) if asked["category"] else None
    category_id, enums = _searched_category(category) if category else (None, {})
    ranges = {}
    if asked["filters"]:
        chosen, ranges = queries.check_filters(asked["filters"], reference()["params"])
        enums = {**enums, **chosen}
    if data.get("price_min") is not None or data.get("price_max") is not None:
        low, high = data.get("price_min"), data.get("price_max")
        if low is not None and high is not None and low > high:
            raise ValueError("price_min is above price_max.")
        given = {k: v for k, v in (("min", low), ("max", high)) if v is not None}
        # over the price a link (or `filters`) carries: its bound that is not given here stays,
        # unless it contradicts the one given (then the param alone wins)
        price = {**ranges.get("price", {}), **given}
        ranges["price"] = given if price.get("min", 0) > price.get("max", float("inf")) else price
    locations = _locations(asked["location"])
    if data.get("radius") and not any("area" in loc for loc in locations):
        raise ValueError("radius needs a city, a postcode or lat,lng in `location` (a department or region has no radius).")
    body = queries.search_body(text=asked["text"], title_only=asked["title_only"], category_id=category_id,
                               locations=locations, radius_km=data.get("radius"),
                               include_delivery=asked["include_delivery"], enums=enums, ranges=ranges,
                               seller_type=asked["seller_type"], ad_type=asked["ad_type"] or "offer",
                               sort=asked["sort"], page=page, limit=limit)
    found = parsers.parse_search(fetch_search(body), page, limit)
    return {
        "query": asked["text"],
        "category": {k: category[k] for k in _CATEGORY_KEYS} if category else None,
        "locations": _location_labels(locations),
        "radius_km": data.get("radius"),
        "seller_type": asked["seller_type"],
        "ad_type": asked["ad_type"] or "offer",
        "sort": asked["sort"],
        "filters": ([{"key": k, "value": "|".join(v)} for k, v in enums.items()]
                    + [{"key": k, "value": f"{v.get('min', 'min')}-{v.get('max', 'max')}"} for k, v in ranges.items()]),
        **found,
    }


def ads_search(**data):
    return cached_call("leboncoin.search", data, _ads_search, ttl.SEARCH_CACHE)


# ---- ads/details, ads/bulk, ads/similar ------------------------------------------------

def _fetch_ads(ids):
    return parsers.parse_bulk(fetch_search(queries.ads_body(ids), label=f"ads {','.join(ids)[:60]}"), ids)


def _ads_details(ad):
    found = _fetch_ads([ad])["ads"]
    if not found:
        raise LeboncoinNotFound(f"ad {ad} not found: it does not exist, or it was removed")
    return found[0]


def ads_details(**data):
    return cached_call("leboncoin.details", data, _ads_details, ttl.AD_CACHE)


def _ads_bulk(ads):
    batch = _fetch_ads(ads)
    return {
        "requested_count": len(ads),
        "found_count": len(batch["ads"]),
        "not_found": batch["not_found"],
        "ads": batch["ads"],
    }


def ads_bulk(**data):
    return cached_call("leboncoin.bulk", data, _ads_bulk, ttl.AD_CACHE)


def _ads_similar(ad, limit):
    rows = parsers.parse_ads(fetch_similar(ad, limit))[:limit]
    return {"ad_id": int(ad), "count": len(rows), "ads": rows}


def ads_similar(**data):
    return cached_call("leboncoin.similar", data, _ads_similar, ttl.SIMILAR_CACHE)


# ---- sellers ---------------------------------------------------------------------------

def _fetch_store(store):
    return fetch_store(store)


def _store(store_id):
    """A store page by its id (cached, raw). Unknown store -> NotFound."""
    try:
        return cached_call("leboncoin.store", {"store": store_id}, _fetch_store, ttl.STORE_CACHE)
    except LeboncoinNotFound:
        raise LeboncoinNotFound(f"store {store_id} not found")


def _user_of(seller):
    """A resolved `seller` -> (user id, the raw store page when the seller
    was given as a store)."""
    store_id = refs.store_id_of(seller)
    if store_id is None:
        return seller, None
    store = _store(store_id)
    user_id = (store.get("owner") or {}).get("userId")
    if not user_id:
        raise LeboncoinNotFound(f"store {store_id} names no owner")
    return user_id.lower(), store


def _card(user_id):
    try:
        return fetch_user_card(user_id)
    except LeboncoinNotFound:
        raise LeboncoinNotFound(f"seller {user_id} not found")


def _sellers_details(seller):
    """A seller in full: the card, and for a pro the company record and the
    store page (whose website the contact lookup reads)."""
    user_id, store = _user_of(seller)
    card = _card(user_id)
    company = None
    if card.get("account_type") == "pro":
        company = fetch_pro_info(user_id)
        if store is None:
            store_id = fetch_store_id(user_id)
            store = _store(store_id) if store_id else None
    return parsers.parse_seller(card, user_id, company=company, store=store, followers=fetch_followers(user_id))


def sellers_details(**data):
    return cached_call("leboncoin.seller", data, _sellers_details, ttl.SELLER_CACHE)


def _sellers_ads(seller, page, limit):
    user_id, _ = _user_of(seller)
    body = queries.search_body(owner_user_id=user_id, sort="newest", page=page, limit=limit)
    found = parsers.parse_search(fetch_search(body, label=f"ads of {user_id}"), page, limit)
    if not found["ads"] and page == 1:
        _card(user_id)          # the site answers no rows for an unknown seller too: tell the two apart
    return {
        "seller_id": user_id,
        "seller_link": refs.profile_link(user_id),
        "ads": found["ads"],
        "pagination": found["pagination"],
    }


def sellers_ads(**data):
    return cached_call("leboncoin.seller_ads", data, _sellers_ads, ttl.SEARCH_CACHE)


def _sellers_reviews(seller, page, limit):
    user_id, _ = _user_of(seller)
    payload = fetch_reviews(user_id, page, limit)
    if payload is None:
        _card(user_id)          # no review yet and an unknown user are the same 404 upstream
    parsed = parsers.parse_reviews(payload, page, limit)
    return {
        "seller_id": user_id,
        "seller_link": refs.profile_link(user_id),
        "summary": parsed["summary"],
        "reviews": parsed["reviews"],
        "pagination": parsed["pagination"],
    }


def sellers_reviews(**data):
    return cached_call("leboncoin.reviews", data, _sellers_reviews, ttl.REVIEWS_CACHE)


# ---- search/suggestions, locations/search ----------------------------------------------

def _categories_by_id():
    """The category names, for the suggestions. They only decorate a row:
    when the reference data cannot be read, the rows go out with ids alone."""
    try:
        return reference()["by_id"]
    except LeboncoinUpstreamError as e:
        print(f"leboncoin: category names skipped for suggestions: {type(e).__name__}: {e}")
        return {}


def _search_suggestions(query):
    rows = parsers.parse_suggestions(fetch_suggestions(query), _categories_by_id())
    return {"query": query, "count": len(rows), "suggestions": rows}


def search_suggestions(**data):
    return cached_call("leboncoin.suggestions", data, _search_suggestions, ttl.SUGGESTIONS_CACHE)


def _locations_search(query):
    rows = parsers.parse_locations(fetch_locations(query))
    return {"query": query, "count": len(rows), "locations": rows}


def locations_search(**data):
    return cached_call("leboncoin.locations", data, _locations_search, ttl.LOCATIONS_CACHE)


# ---- categories ------------------------------------------------------------------------

def _categories_list():
    tree = reference()["categories"]
    return {
        "count": sum(1 + len(c["subcategories"]) for c in tree),
        "categories": tree,
    }


def categories_list(**data):
    return cached_call("leboncoin.categories", data, _categories_list, ttl.CATEGORIES_CACHE)


def _categories_filters(category, filters):
    ref = reference()
    record = _category(category)
    form_id = (record["same_as"] or {}).get("category_id") or record["id"]
    chosen = queries.chosen_values(filters, ref["params"]) if filters else {}
    unknown = [key for key, _ in filters or [] if key not in ref["params"]]
    if unknown:
        raise ValueError(f"filters: the site has no filter named '{unknown[0]}'.")
    rows = parsers.parse_category_filters(ref, form_id, chosen)
    return {
        "category": {k: record[k] for k in _CATEGORY_KEYS},
        "count": len(rows),
        "filters": rows,
    }


def categories_filters(**data):
    return cached_call("leboncoin.category_filters", data, _categories_filters, ttl.CATEGORIES_CACHE)
