"""The bodies of leboncoin's search call, built the way its own pages build
them (pure functions, no I/O).

What the site's pages send to POST /finder/search (2026-11-20; `search` in
the page data of /recherche?category=2&u_car_brand=PEUGEOT&mileage=min-100000
&fuel=1&owner_type=pro&regdate=2018-max&locations=d_69):

    {"filters": {"enums": {"ad_type": ["offer"], "u_car_brand": ["PEUGEOT"], "fuel": ["1"]},
                 "category": {"id": "2"},
                 "keywords": {"text": "...", "type": "subject"},          # type only for "title only"
                 "location": {"shippable": true, "locations": [{...}]},   # shippable: also ads delivered from elsewhere
                 "ranges": {"mileage": {"max": 100000}, "regdate": {"min": 2018}},
                 "owner": {"user_id": "<uuid>"}},                         # a seller's ads
     "sort_by": "relevance", "sort_order": "asc", "owner_type": "pro", "limit": 35, "offset": 35}

The pages also send "inject_alu": true, which makes the site put two paid
"à la une" ads on top of page 1: left out here, so a page holds only what
the search found.

Ads by id: the answer's own `pivot` lists the ids of the next pages
(`ids_to_display`); a body whose pivot names ids is answered with exactly
those ads, whatever the filters, up to 100 a call.
"""
import json

from leboncoin import refs

DEFAULT_LIMIT = 35      # the site's own page size
MAX_LIMIT = 100         # limit=200 and 500 are answered as 100 (2026-11-20)
MAX_RADIUS_KM = 200     # 100 and 200 km both answered (2026-11-20)


def _with_radius(location, radius_km):
    """A city / place / point with the caller's radius (metres upstream,
    next to the city's own default_radius, as the site's links carry it);
    areas (department, region) have none."""
    if not radius_km or "area" not in location:
        return location
    return {**location, "area": {**location["area"], "radius": int(radius_km) * 1000}}


def search_body(text=None, title_only=False, category_id=None, locations=None, radius_km=None,
                include_delivery=False, enums=None, ranges=None, owner_user_id=None, seller_type=None,
                ad_type="offer", sort="relevance", page=1, limit=DEFAULT_LIMIT):
    """The body of one search page (page is 1-based; the site takes an offset)."""
    filters = {"enums": {"ad_type": [ad_type or "offer"], **(enums or {})}}
    if category_id:
        filters["category"] = {"id": str(category_id)}
    if text:
        filters["keywords"] = {"text": text, "type": "subject"} if title_only else {"text": text}
    location = {}
    if include_delivery:
        location["shippable"] = True
    if locations:
        location["locations"] = [_with_radius(loc, radius_km) for loc in locations]
    if location:
        filters["location"] = location
    if ranges:
        filters["ranges"] = ranges
    if owner_user_id:
        filters["owner"] = {"user_id": owner_user_id}
    sort_by, sort_order = refs.SORTS[sort or "relevance"]
    body = {"filters": filters, "sort_by": sort_by, "limit": min(int(limit), MAX_LIMIT)}
    if sort_order:
        body["sort_order"] = sort_order
    if seller_type:
        body["owner_type"] = seller_type
    offset = (max(int(page), 1) - 1) * body["limit"]
    if offset:
        body["offset"] = offset
    return body


def ads_body(ids):
    """The body that answers exactly these ads (at most MAX_LIMIT)."""
    ids = [str(i) for i in ids][:MAX_LIMIT]
    return {"filters": {}, "limit": max(len(ids), 1), "pivot": json.dumps({"ids_to_display": ids}, separators=(",", ":"))}


# ---- the caller's filters against the site's filter list -------------------------------

def parse_range(key, text):
    """'500-1500' / 'min-100000' / '2018-max' / '3' -> {"min": .., "max": ..}."""
    low, sep, high = str(text).strip().partition("-")
    if not sep:
        high = low

    def bound(value, open_word):
        value = value.strip().lower()
        if value in ("", open_word):
            return None
        if not value.isdigit():
            raise ValueError(f"filters: '{key}' is a range: write it {key}:min-max, {key}:min-100000 or {key}:2018-max.")
        return int(value)
    lower, upper = bound(low, "min"), bound(high, "max")
    if lower is None and upper is None:
        raise ValueError(f"filters: '{key}' needs at least one bound ({key}:min-100000 or {key}:2018-max).")
    if lower is not None and upper is not None and lower > upper:
        raise ValueError(f"filters: '{key}' has its bounds the wrong way round.")
    return {k: v for k, v in (("min", lower), ("max", upper)) if v is not None}


def _choice(key, text, entry):
    tokens = []
    for raw in str(text).split("|"):
        wanted = raw.strip()
        if not wanted:
            continue
        token = entry["values"].get(wanted.casefold()) or entry["labels"].get(wanted.casefold())
        if token is None:
            if not entry["open"]:
                known = list(entry["values"].values())
                shown = ", ".join(known[:12]) + (f" … ({len(known)} values)" if len(known) > 12 else "")
                raise ValueError(f"filters: '{key}' has no value '{wanted}'. Its values: {shown}.")
            token = wanted
        if token not in tokens:
            tokens.append(token)
    if not tokens:
        raise ValueError(f"filters: '{key}' has no value.")
    return tokens


def check_filters(pairs, params):
    """[[key, text]] checked against the reference's filter keys ->
    (enums, ranges) for the search body. An unknown key or value is a
    ValueError: the site would answer it with nothing, or ignore it."""
    enums, ranges = {}, {}
    for key, text in pairs or []:
        if key in refs.FLAG_FILTERS:
            if str(text).strip().lower() not in ("1", "true"):
                raise ValueError(f"filters: '{key}' is a switch: write {key}:1.")
            enums[key] = ["1"]
            continue
        entry = params.get(key)
        if entry is None:
            raise ValueError(f"filters: the site has no filter named '{key}'. /leboncoin/categories/filters lists "
                             "the filters of a category.")
        if entry.get("is_date"):
            raise ValueError(f"filters: '{key}' is a date range (holiday rentals), which this API does not take.")
        if entry["type"] == "range":
            ranges[key] = parse_range(key, text)
        else:
            enums[key] = _choice(key, text, entry)
    return enums, ranges


def chosen_values(pairs, params):
    """[[key, text]] -> {key: [tokens]} for the choice filters among them
    (categories/filters uses it to open the filters that depend on one)."""
    enums, _ = check_filters([p for p in pairs or [] if params.get(p[0], {}).get("type") == "choice"], params)
    return enums
