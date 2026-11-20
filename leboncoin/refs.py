"""Reference resolvers, link builders and the choice tables for /leboncoin/*.

ONE param per input: `ad` accepts an ad id OR a leboncoin.fr ad link;
`seller` a user id, a profile link OR a pro store ("boutique") link;
`query` keywords OR a whole leboncoin.fr search link; `category` a category
id, its slug OR a category link. Resolvers raise ValueError with a
user-facing message (RefField turns it into a 400).

Identifier shapes (www.leboncoin.fr, 2026-11-20):
  * ad        `list_id`, 10 digits today (3091399005; old ads have fewer).
              The last path segment of an ad link:
              /ad/<category slug>/<id>  (older links: /<category>/<id>.htm).
  * seller    a UUID, the ad's owner.user_id; /profile/<uuid>/offers.
  * store     a pro seller's public page, /boutique/<online store id>/<slug>.htm
              (338302). It is NOT the ad's owner.store_id (26969202), which
              is the seller's account number and opens no page.
  * category  a number as text ("2" Voitures, "9" Ventes immobilières); its
              slug is the site's `deeplink` (voitures), as in /c/voitures.
  * location  the site's own link tokens: a city
              `Lyon_69003__45.75898_4.86114_3774` (name, optional postcode,
              then lat_lng_default radius[_radius] in metres; the name and
              postcode are what the site matches, the radius widens it), a department
              `d_69`, a region `r_22`, a tourist place `p_<name>__lat_lng_radius`.
              `dn_69` / `rn_22` (the department / region with its neighbours)
              are this API's own spelling of the site's "et départements
              voisins" choices.
"""
import re
from urllib.parse import parse_qsl, unquote, urlparse

SITE = "https://www.leboncoin.fr"
HOSTS = ("leboncoin.fr",)

AD_ID_RE = re.compile(r"^[0-9]{5,12}$")
USER_ID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)
STORE_ID_RE = re.compile(r"^[0-9]{1,9}$")
STORE_PREFIX = "boutique:"          # how a store reference is carried once resolved

MAX_BULK_ADS = 100                  # the search call serves at most 100 rows (170 ids asked, 100 answered, 2026-11-20)
MAX_LOCATIONS = 10
MAX_LOCATION_LENGTH = 120
MAX_FILTERS = 20
# metres around a bare "lat,lng". A named city is matched by its name and postcode; a bare point is matched
# only by `radius` (`default_radius` alone is ignored there: 1,447,846 ads against 14,175, 2026-11-20)
DEFAULT_COORDINATES_RADIUS = 10000

_AD_HELP = ("Must be a leboncoin ad id (3091399005) or an ad link "
            "(https://www.leboncoin.fr/ad/telephones_objets_connectes/3091399005).")
_SELLER_HELP = ("Must be a seller's user id (031c778f-f4bd-4969-98a8-179c1f4efd2f), a profile link "
                "(https://www.leboncoin.fr/profile/<user id>/offers) or a pro store link "
                "(https://www.leboncoin.fr/boutique/338302/...).")
_CATEGORY_HELP = "Must be a category id (2), its slug (voitures) or a category link (https://www.leboncoin.fr/c/voitures)."
_LOCATION_HELP = ("Must be a place name or postcode (Lyon, 33000, Bretagne), lat,lng (45.76,4.83), or a `value` "
                  "from /leboncoin/locations/search (d_69, r_22, Lyon_69003__45.75898_4.86114_3774); "
                  "several are separated by ';'.")
_FILTERS_HELP = ("Must be key:value pairs separated by commas, with the keys and values of "
                 "/leboncoin/categories/filters: fuel:1|2 for several values, mileage:min-100000 or "
                 "regdate:2018-max for a range.")


def _site_url(value):
    """A leboncoin.fr link or bare site path -> its parsed URL (None when
    the value is neither); a link to another host raises ValueError."""
    if value.startswith("/") and not value.startswith("//"):
        return urlparse(SITE + value)
    if not value.startswith(("http://", "https://", "//", "www.leboncoin.fr/", "leboncoin.fr/")):
        return None
    url = value
    if url.startswith("//"):
        url = "https:" + url
    elif not url.startswith("http"):
        url = "https://" + url
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if not any(host == h or host.endswith("." + h) for h in HOSTS):
        raise ValueError("Must be a leboncoin.fr link.")
    return parsed


def _segments(parsed):
    return [unquote(p) for p in (parsed.path or "").split("/") if p]


# ---- ads -----------------------------------------------------------------------------

# first path segments whose second segment is a number of another kind
# (/boutique/338302 is a store, not the old /<category>/<id>.htm ad link)
_NOT_AD_SECTIONS = ("boutique", "profile", "recherche", "c", "cl")


def _ad_id_of_path(parts):
    if not parts:
        return None
    last = re.sub(r"\.html?$", "", parts[-1])
    if AD_ID_RE.match(last) and (len(parts) >= 2 or parts[0] != "recherche"):
        return last
    return None


def resolve_ad(value):
    """Ad id or ad link -> the id, as text."""
    value = (value or "").strip()
    parsed = _site_url(value)
    if parsed is not None:
        parts = _segments(parsed)
        if parts and parts[0] in ("ad", "vi", "offre") or len(parts) == 2 and parts[0] not in _NOT_AD_SECTIONS:
            found = _ad_id_of_path(parts)
            if found:
                return found
        raise ValueError(_AD_HELP)
    if AD_ID_RE.match(value):
        return value
    raise ValueError(_AD_HELP)


def resolve_ads(value):
    """'3091399005, <link>, ...' -> the ids in the order given, repeats
    dropped. At most MAX_BULK_ADS."""
    ids = []
    for raw in str(value or "").split(","):
        item = raw.strip()
        if not item:
            continue
        found = resolve_ad(item)
        if found not in ids:
            ids.append(found)
    if not ids:
        raise ValueError(_AD_HELP)
    if len(ids) > MAX_BULK_ADS:
        raise ValueError(f"At most {MAX_BULK_ADS} ads per call.")
    return ids


# ---- sellers -------------------------------------------------------------------------

def resolve_seller(value):
    """User id, profile link or store link -> the user id (lower case), or
    'boutique:<online store id>' for a store, which api.py maps to its owner."""
    value = (value or "").strip()
    parsed = _site_url(value)
    if parsed is not None:
        parts = _segments(parsed)
        if len(parts) >= 2 and parts[0] == "profile" and USER_ID_RE.match(parts[1]):
            return parts[1].lower()
        if len(parts) >= 2 and parts[0] == "boutique" and STORE_ID_RE.match(parts[1]):
            return STORE_PREFIX + str(int(parts[1]))
        raise ValueError(_SELLER_HELP)
    if USER_ID_RE.match(value):
        return value.lower()
    if value.lower().startswith(STORE_PREFIX) and STORE_ID_RE.match(value[len(STORE_PREFIX):]):
        return STORE_PREFIX + str(int(value[len(STORE_PREFIX):]))
    if STORE_ID_RE.match(value):
        return STORE_PREFIX + str(int(value))
    raise ValueError(_SELLER_HELP)


def store_id_of(seller):
    """The online store id of a resolved 'boutique:<id>' reference, else None."""
    if isinstance(seller, str) and seller.startswith(STORE_PREFIX):
        return int(seller[len(STORE_PREFIX):])
    return None


# ---- categories ----------------------------------------------------------------------

_CATEGORY_RE = re.compile(r"^[A-Za-z0-9_àâäçéèêëîïôöùûüœ' &-]{1,80}$")


def resolve_category(value):
    """Category id, slug, name or category link -> the id or the slug / name
    as written (api.py finds it in the site's category list)."""
    value = (value or "").strip()
    parsed = _site_url(value)
    if parsed is not None:
        parts = _segments(parsed)
        if len(parts) >= 2 and parts[0] in ("c", "cl"):
            return parts[1]
        query = dict(parse_qsl(parsed.query))
        if parts[:1] == ["recherche"] and query.get("category"):
            return query["category"].strip()
        raise ValueError(_CATEGORY_HELP)
    if _CATEGORY_RE.match(value):
        return value
    raise ValueError(_CATEGORY_HELP)


# ---- locations -----------------------------------------------------------------------

_NUMBER = r"-?[0-9]{1,3}(?:\.[0-9]+)?"
_COORDINATES_RE = re.compile(rf"^({_NUMBER})\s*,\s*({_NUMBER})$")
_AREA_TOKEN_RE = re.compile(r"^[a-z]{1,2}_[0-9A-Za-z]{1,3}$")
_AREA_TYPES = {"d": ("department", "department_id"), "dn": ("department_near", "department_id"),
               "r": ("region", "region_id"), "rn": ("region_near", "region_id")}
_POINT_RE = re.compile(rf"^(?P<name>.*?)__(?P<lat>{_NUMBER})_(?P<lng>{_NUMBER})(?:_(?P<first>[0-9]+))?(?:_(?P<second>[0-9]+))?$")


def _checked_point(lat, lng):
    lat, lng = float(lat), float(lng)
    if not (-90 <= lat <= 90 and -180 <= lng <= 180):
        raise ValueError("Latitude must be -90..90 and longitude -180..180.")
    return lat, lng


def _one_location(item):
    """One location as the site's search call takes it, or {"text": ...}
    for a name the site's own location search has to place."""
    match = _COORDINATES_RE.match(item)
    if match:
        lat, lng = _checked_point(match.group(1), match.group(2))
        return {"locationType": "city", "label": f"{lat},{lng}",
                "area": {"lat": lat, "lng": lng, "radius": DEFAULT_COORDINATES_RADIUS}}
    if _AREA_TOKEN_RE.match(item) and item.split("_", 1)[0].lower() in _AREA_TYPES:
        prefix, number = item.split("_", 1)
        kind, key = _AREA_TYPES[prefix.lower()]
        return {"locationType": kind, key: number.upper()}
    match = _POINT_RE.match(item)
    if match:
        lat, lng = _checked_point(match.group("lat"), match.group("lng"))
        area = {"lat": lat, "lng": lng}
        if match.group("first"):
            area["default_radius"] = int(match.group("first"))
        if match.group("second"):
            area["radius"] = int(match.group("second"))
        name = match.group("name").strip()
        if name.startswith("p_"):
            return {"locationType": "place", "place": name[2:], "label": name[2:], "area": area}
        if not name:
            # a point with no city name: the site honours only `radius` there
            return {"locationType": "city", "label": f"{lat},{lng}",
                    "area": {"lat": lat, "lng": lng,
                             "radius": area.get("radius") or area.get("default_radius") or DEFAULT_COORDINATES_RADIUS}}
        out = {"locationType": "city", "area": area}
        zipped = re.match(r"^(.*?)_([0-9]{5})$", name)
        if zipped:
            name, out["zipcode"] = zipped.group(1), zipped.group(2)
        if name:
            out["city"] = name
        out["label"] = " ".join(p for p in (name, f"({out['zipcode']})" if out.get("zipcode") else "") if p) or f"{lat},{lng}"
        return out
    if "__" in item or len(item) > MAX_LOCATION_LENGTH:
        raise ValueError(_LOCATION_HELP)
    return {"text": item}


def resolve_location(value, separator=";"):
    """'Lyon; d_69; 45.76,4.83' -> a list of locations: each one the site's
    own location object, or {"text": name} when the site has to place it."""
    found = []
    for raw in str(value or "").split(separator):
        item = " ".join(raw.split())
        if not item:
            continue
        location = _one_location(item)
        if location not in found:
            found.append(location)
    if not found:
        raise ValueError(_LOCATION_HELP)
    if len(found) > MAX_LOCATIONS:
        raise ValueError(f"At most {MAX_LOCATIONS} locations.")
    return found


def location_token(location):
    """The `location` value that selects one of the site's location objects
    again (the `value` of a /locations/search row)."""
    kind = location.get("locationType")
    for prefix, (name, key) in _AREA_TYPES.items():
        if kind == name and location.get(key):
            return f"{prefix}_{location[key]}"
    area = location.get("area") or {}
    if area.get("lat") is None or area.get("lng") is None:
        return None
    tail = f"__{area['lat']}_{area['lng']}" + (f"_{area['default_radius']}" if area.get("default_radius") else "")
    if kind == "place":
        return f"p_{location.get('place') or location.get('label') or ''}{tail}"
    name = location.get("city") or ""
    if location.get("zipcode"):
        name = f"{name}_{location['zipcode']}"
    return name + tail


# ---- filters -------------------------------------------------------------------------

_FILTER_KEY_RE = re.compile(r"^[a-z][a-z0-9_]{0,59}$")


def resolve_filters(value):
    """'fuel:1|2, mileage:min-100000' -> [["fuel", "1|2"], ["mileage",
    "min-100000"]] (api.py checks each key and value against the site's
    filter list)."""
    pairs = []
    for raw in str(value or "").split(","):
        item = raw.strip()
        if not item:
            continue
        key, sep, val = item.partition(":")
        key, val = key.strip().lower(), val.strip()
        if not sep or not val or not _FILTER_KEY_RE.match(key):
            raise ValueError(f"'{item}' is not key:value. {_FILTERS_HELP}")
        if any(key == k for k, _ in pairs):
            raise ValueError(f"The filter '{key}' is given twice; write its values as {key}:a|b.")
        pairs.append([key, val])
    if not pairs:
        raise ValueError(_FILTERS_HELP)
    if len(pairs) > MAX_FILTERS:
        raise ValueError(f"At most {MAX_FILTERS} filters.")
    return pairs


# ---- search links --------------------------------------------------------------------

# what a /recherche link names itself; every other param is one of the site's filters
_LINK_KNOWN = ("text", "search_in", "category", "locations", "sort", "order", "owner_type", "shippable", "page", "ad_type")
_LINK_SKIPPED = ("kst", "referrer_id", "from", "utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term")


def is_link(value):
    return value.startswith(("http://", "https://", "//", "www.leboncoin.fr/", "leboncoin.fr/"))


def resolve_search_link(value):
    """A leboncoin.fr search link -> what it asks for, in this API's own
    params (still as text): {"query", "category", "location", "sort",
    "seller_type", "ad_type", "title_only", "include_delivery", "page",
    "filters": [[key, value]]}. Two link forms: /recherche?<params> and
    /c/<category slug>[/<key>:<value>...]."""
    parsed = _site_url((value or "").strip())
    if parsed is None:
        raise ValueError("Must be a leboncoin.fr search link.")
    parts = _segments(parsed)
    out, filters = {}, []
    if parts[:1] == ["recherche"]:
        pass
    elif len(parts) >= 2 and parts[0] in ("c", "cl"):
        out["category"] = parts[1]
        for segment in parts[2:]:
            key, sep, val = segment.partition(":")
            if sep and _FILTER_KEY_RE.match(key) and val:
                filters.append([key, val.replace(",", "|")])
    elif _ad_id_of_path(parts) and parts[0] in ("ad", "vi", "offre"):
        raise ValueError("That is an ad link: /leboncoin/ads/details reads one ad. `query` takes keywords or a search link.")
    elif parts[:1] in (["profile"], ["boutique"]):
        raise ValueError("That is a seller link: /leboncoin/sellers/ads lists a seller's ads. `query` takes keywords or a search link.")
    else:
        raise ValueError("Must be a leboncoin.fr search link (https://www.leboncoin.fr/recherche?... or /c/<category>).")
    for key, val in parse_qsl(parsed.query, keep_blank_values=False):
        key, val = key.strip(), val.strip()
        if not val or key in _LINK_SKIPPED:
            continue
        if key == "text":
            out["query"] = " ".join(val.split())
        elif key == "search_in":
            out["title_only"] = val == "subject"
        elif key == "category":
            out["category"] = val
        elif key == "locations":
            out["location"] = resolve_location(val, separator=",")
        elif key == "sort":
            out["sort_by"] = val
        elif key == "order":
            out["sort_order"] = val
        elif key == "owner_type":
            out["seller_type"] = val
        elif key == "ad_type":
            out["ad_type"] = val
        elif key == "shippable":
            out["include_delivery"] = val == "1"
        elif key == "page":
            if val.isdigit() and int(val) >= 1:
                out["page"] = int(val)
        elif _FILTER_KEY_RE.match(key):
            filters.append([key, val.replace(",", "|")])
        else:
            raise ValueError(f"The link carries a parameter this API cannot read: {key!r}.")
    sort_by, sort_order = out.pop("sort_by", None), out.pop("sort_order", None)
    if sort_by:
        wanted = (sort_by, sort_order if sort_by != "relevance" else None)
        match = next((name for name, token in SORTS.items() if token == wanted), None)
        if match is None and sort_by in ("time", "price"):
            match = next(name for name, token in SORTS.items() if token[0] == sort_by)      # the site's default order for it
        if match is None:
            raise ValueError(f"The link asks for a sort this API does not know: {sort_by!r}.")
        out["sort"] = match
    if filters:
        out["filters"] = filters
    return out


def resolve_query(value):
    """`query`: keywords -> {"text": ...}; a leboncoin.fr search link ->
    {"link": resolve_search_link(...)}."""
    value = " ".join((value or "").split())
    if is_link(value):
        return {"link": resolve_search_link(value)}
    if len(value) > 200:
        raise ValueError("Longer than maximum length 200.")
    return {"text": value}


# ---- links ---------------------------------------------------------------------------

def ad_link(ad_id, category_slug=None):
    return f"{SITE}/ad/{category_slug or 'annonce'}/{ad_id}" if ad_id else None


def profile_link(user_id):
    return f"{SITE}/profile/{user_id}/offers" if user_id else None


def store_link(store_id):
    return f"{SITE}/boutique/{store_id}" if store_id else None


def category_link(slug):
    return f"{SITE}/c/{slug}" if slug else None


# ---- choice tables -------------------------------------------------------------------

# public sort name -> (sort_by, sort_order) of the search call. The site's
# own sort menu: Pertinence, Plus récentes, Plus anciennes, Prix croissants,
# Prix décroissants (each answered in that order on 2026-11-20)
SORTS = {
    "relevance": ("relevance", None),
    "newest": ("time", "desc"),
    "oldest": ("time", "asc"),
    "price_asc": ("price", "asc"),
    "price_desc": ("price", "desc"),
}

SELLER_TYPES = {"private": "private", "pro": "pro"}     # the call's owner_type
AD_TYPES = {"offer": "offer", "demand": "demand"}       # an ad that sells / an ad that looks for something

# the two filters every category has and the site's filter list does not carry
FLAG_FILTERS = ("urgent", "donation")
