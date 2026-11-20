"""JSON -> clean dicts for every /leboncoin/* endpoint. Pure functions, no I/O.

Fixtures (leboncoin/fixtures/, raw answers of api.leboncoin.fr captured on
2026-11-20 through leboncoin/fetch.py, untrimmed):

  search_iphone_15.json          /finder/search, keyword, 5 rows
  search_cars_filters.json       the same call with a category, a brand, two ranges, a department, pros only
  search_rentals_lyon.json       real-estate rows (rent, charges, energy class, district)
  search_no_result.json          a search that finds nothing
  search_past_end.json           an offset past the 3,500-row depth
  ads_by_id.json                 /finder/search with ids in `pivot`: a pro ad, a private ad, one unknown id
  ads_by_id_not_found.json       the same call for an id the site does not have
  search_demand.json             wanted ads (ad_type demand): no price, often no image
  similar_ads.json               /api/vs-recommendation-api/v1/search/<id>
  seller_private_rated.json      /api/user-card/v2/<id>/infos, a private seller with reviews
  seller_private_plain.json      ... one without a review
  seller_pro.json                ... a pro
  seller_pro_company.json        /api/users/v1/users/pro-public-info/<id>
  store_338302.json              /api/onlinestores/v1/online_stores/<id>
  store_agency.json              ... a real-estate agency (team, activity zone, sold properties)
  store_rated.json               ... a car dealer whose page shows its Google Maps rating
  followers.json                 /api/followme/v1/followers-number/<id>
  reviews_page_1.json            /api/trust-feedback/public/users/<urn>/feedback?limit=5&page=0
  reviews_past_end.json          ... a page past the end
  reviews_not_found.json         ... the 404 body of a user without reviews
  suggestions_iphone.json        /api/parrot/v3/complete
  locations_lyon.json            /api/parrot-location/v2/complete/location
  locations_rhone.json           ... departments, regions, a tourist place
  fdata.json.gz                  /api/frontend/v1/data/v7/fdata (categories, regions, 697 filters)
  fforms.json                    /api/frontend/v1/data/v5/fforms (which filters a category has)
  blocked_captcha.json           a DataDome answer (HTTP 403)
  blocked_page.html              its HTML form

Units as the site sends them: `price_cents` is exact, `price` is whole
euros in a list; fees are cents; every amount here is euros. Ad dates are
Paris wall-clock time with no offset ("2026-10-05 11:44:46") and come out
as UTC. Scores are 0-1 (0.98); the site shows them times 5, and so do we.
"""
import re

from leboncoin import refs
from scraper_utils.dates import iso_day, iso_utc, wall_clock_utc
from scraper_utils.text import clean, multiline
from scraper_utils.values import amount, as_dict, as_list, g, num, rounded, to_int

CURRENCY = "EUR"
SITE_ZONE = "Europe/Paris"

# attributes that are read into a field of their own (and so are not repeated in `attributes`)
_USED_ATTRIBUTES = {
    "rating_score", "rating_count", "profile_picture_url", "store_logo", "store_name", "online_store_id",
    "old_price", "shippable", "shipping_type", "estimated_parcel_weight", "estimated_parcel_size",
    "payment_methods", "donation", "stock_quantity", "custom_ref", "activity_sector", "country_isocode3166",
    "pro_rates_link",
}
# attributes that only steer the site's own page
_PAGE_ATTRIBUTES = {
    "purchase_cta_visible", "negotiation_cta_visible", "is_bundleable", "has_visibility_option",
    "district_id", "district_visibility", "district_type_id", "district_resolution_type", "floor_display",
    "has_tenant_pass_early_access", "argus_object_id", "pricing_product",
}


def _text(value):
    return clean(value) if isinstance(value, str) else None


def _euros(cents):
    """Cents -> euros (44990 -> 449.9); None for None / junk."""
    value = num(cents)
    return amount(value / 100) if value is not None else None


def _stars(score):
    """A 0-1 score -> the 0-5 rating the site shows (0.98 -> 4.9)."""
    value = num(score)
    return rounded(value * 5, 2) if value is not None else None


def _flag(value):
    """The site's text booleans ("true" / "false" / "1" / "2"=no) -> bool or None."""
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower() if value is not None else ""
    if text in ("true", "1"):
        return True
    if text in ("false", "0", "2"):
        return False
    return None


def _snake(name):
    """'VerifiedPhoneNumber' -> 'verified_phone_number'."""
    if not isinstance(name, str) or not name:
        return None
    return re.sub(r"[^a-z0-9]+", "_", re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", name).lower()).strip("_") or None


def _user_id(urn):
    """'sdrn:leboncoin:user:<uuid>' -> the uuid."""
    return urn.rsplit(":", 1)[-1] if isinstance(urn, str) and urn else None


# ---- ads -----------------------------------------------------------------------------

_DAY_FIRST_RE = re.compile(r"^(\d{2})/(\d{2})/(\d{4})$")


def _iso_if_date(text):
    """The site's day-first date ('24/08/2026') -> '2026-08-24'; anything
    else (a month like '07/2022' included) as it is."""
    match = _DAY_FIRST_RE.match(text) if isinstance(text, str) else None
    if match and 1 <= int(match.group(2)) <= 12 and 1 <= int(match.group(1)) <= 31:
        return f"{match.group(3)}-{match.group(2)}-{match.group(1)}"
    return text


def _attribute(raw):
    values = [str(v) for v in as_list(raw.get("values")) if v not in (None, "")]
    value = raw.get("value")
    if value in (None, "") and values:
        value = ", ".join(values)
    labels = as_list(raw.get("values_label"))
    label = _text(raw.get("value_label")) or (", ".join(str(v) for v in labels) if labels else None)
    return {
        "key": raw.get("key"),
        "name": _text(raw.get("key_label")),
        "value": _iso_if_date(str(value)) if value not in (None, "") else None,
        "label": _iso_if_date(label),
    }


def _attributes(raw):
    out = []
    for item in as_list(raw.get("attributes")):
        if not isinstance(item, dict) or not item.get("key"):
            continue
        if item["key"] in _USED_ATTRIBUTES or item["key"] in _PAGE_ATTRIBUTES:
            continue
        out.append(_attribute(item))
    return out


def _attribute_values(raw):
    """{key: [value, values]} of an ad's attributes (lists: g() walks lists, not tuples)."""
    found = {}
    for item in as_list(raw.get("attributes")):
        if isinstance(item, dict) and item.get("key"):
            values = [v for v in as_list(item.get("values")) if v not in (None, "")]
            found[item["key"]] = [item.get("value") if item.get("value") not in (None, "") else (values[0] if values else None), values]
    return found


def _highlights(raw):
    """The plus points the site prints on the ad ("Annonce récente",
    "Parking / Garage"), as it words them."""
    out = []
    for item in as_list(raw.get("attributes_adview_positive")):
        label = _text(as_dict(item).get("value_label"))
        if label and label not in out:
            out.append(label)
    return out


def _category_slug(link):
    match = re.search(r"/ad/([^/]+)/\d+", link or "")
    return match.group(1) if match else None


def _images(raw):
    images = as_dict(raw.get("images"))
    links = [u for u in (as_list(images.get("urls_large")) or as_list(images.get("urls"))) if isinstance(u, str)]
    plans = [c.get("url") for c in as_list(images.get("classifications")) if isinstance(c, dict) and c.get("is_plan") and c.get("url")]
    return {
        "count": to_int(images.get("nb_images")) or 0,
        "thumbnail": images.get("thumb_url") or None,
        "links": links,
        "floor_plan_links": plans,
    }


def _videos(raw):
    out = []
    for video in as_list(g(raw, "extended_attributes", "videos", default=None)):
        if isinstance(video, dict) and video.get("url"):
            out.append({"id": video.get("video_provider_id") or None, "provider": video.get("provider_name") or None,
                        "link": video["url"]})
    return out


def _ad_location(raw):
    location = as_dict(raw.get("location"))
    point = as_list(g(location, "feature", "geometry", "coordinates", default=None))
    longitude, latitude = (num(point[0]), num(point[1])) if len(point) == 2 else (None, None)
    return {
        "label": _text(location.get("city_label")),
        "address": _text(location.get("address")),
        "city": _text(location.get("city")),
        "zipcode": _text(location.get("zipcode")),
        "district": _text(location.get("district")),
        "department": {"id": _text(location.get("department_id")), "name": _text(location.get("department_name"))},
        "region": {"id": _text(location.get("region_id")), "name": _text(location.get("region_name"))},
        "country": _text(location.get("country_id")),
        "latitude": latitude if latitude is not None else num(location.get("lat")),
        "longitude": longitude if longitude is not None else num(location.get("lng")),
        "precision": _text(location.get("source")),
        "is_area": location.get("is_shape") if isinstance(location.get("is_shape"), bool) else None,
    }


def _ad_seller(raw, attrs):
    owner = as_dict(raw.get("owner"))
    user_id = _text(owner.get("user_id"))
    store_id = to_int(g(attrs, "online_store_id", 0, default=None))
    store = None
    if store_id or g(attrs, "store_name", 0, default=None):
        store = {"id": store_id, "name": _text(g(attrs, "store_name", 0, default=None)),
                 "link": refs.store_link(store_id), "logo": g(attrs, "store_logo", 0, default=None)}
    return {
        "id": user_id,
        "name": _text(owner.get("name")),
        "link": refs.profile_link(user_id),
        "type": _text(owner.get("type")),
        "account_id": _text(owner.get("store_id")),
        "picture": g(attrs, "profile_picture_url", 0, default=None),
        "rating": _stars(g(attrs, "rating_score", 0, default=None)),
        "reviews_count": to_int(g(attrs, "rating_count", 0, default=None)),
        "siren": _text(owner.get("siren")),
        "activity_sector_id": to_int(owner.get("activity_sector")),
        "rates_link": _text(owner.get("pro_rates_link")) or _text(g(attrs, "pro_rates_link", 0, default=None)),
        "is_solicitation_refused": owner.get("no_salesmen") if isinstance(owner.get("no_salesmen"), bool) else None,
        "store": store,
    }


def _shipping(raw, attrs):
    fees = []
    for fee in as_list(raw.get("shipping_fees")):
        if isinstance(fee, dict) and fee.get("shipping_type"):
            fees.append({"method": fee["shipping_type"], "amount": _euros(fee.get("price")), "currency": CURRENCY})
    return {
        "is_shippable": _flag(g(attrs, "shippable", 0, default=None)),
        "methods": [str(v) for v in g(attrs, "shipping_type", 1, default=[])],
        "fees": fees,
        "parcel_weight_grams": to_int(g(attrs, "estimated_parcel_weight", 0, default=None)),
        "parcel_size": _text(g(attrs, "estimated_parcel_size", 0, default=None)),
        "ships_from_country": _text(g(attrs, "country_isocode3166", 0, default=None)),
    }


def _price(raw, attrs):
    exact = _euros(raw.get("price_cents"))
    if exact is None:
        listed = as_list(raw.get("price"))
        exact = amount(num(listed[0])) if listed and num(listed[0]) is not None else None
    previous = num(g(attrs, "old_price", 0, default=None))
    return {
        "amount": exact,
        "currency": CURRENCY if exact is not None else None,
        "previous_amount": amount(previous) if previous is not None else None,
        "buyer_protection_fee": _euros(g(raw, "buyer_fee", "amount", default=None)),
        "is_free": True if _flag(g(attrs, "donation", 0, default=None)) else False,
        "installments": [str(v) for v in g(attrs, "payment_methods", 1, default=[])],
    }


def _promotion(raw):
    options = as_dict(raw.get("options"))

    def on(key):
        return options.get(key) if isinstance(options.get(key), bool) else None
    boosted = raw.get("is_boosted") if isinstance(raw.get("is_boosted"), bool) else on("booster")
    return {
        "is_boosted": boosted,
        "is_highlighted": on("highlight"),
        "is_top_listed": on("sub_toplist"),
        "has_gallery": on("gallery"),
        "has_extra_photos": on("photosup"),
        "has_continuous_top": on("continuous_top_ads"),
        "has_paid_option": on("has_option"),
    }


def parse_ad(raw):
    """One ad of a search answer (the by-id call and the similar-ads call
    return the same record)."""
    if not isinstance(raw, dict):
        return None
    attrs = _attribute_values(raw)
    link = raw.get("url") or None
    slug = _category_slug(link)
    ad_id = to_int(raw.get("list_id"))
    return {
        "id": ad_id,
        "title": _text(raw.get("subject")),
        "link": link or refs.ad_link(ad_id, slug),
        "status": _text(raw.get("status")),
        "ad_type": _text(raw.get("ad_type")),
        "description": multiline(raw.get("body")) if isinstance(raw.get("body"), str) else None,
        "category": {"id": _text(raw.get("category_id")), "name": _text(raw.get("category_name")), "slug": slug},
        "price": _price(raw, attrs),
        "is_urgent": g(raw, "options", "urgent", default=None) if isinstance(g(raw, "options", "urgent", default=None), bool) else None,
        "has_phone": raw.get("has_phone") if isinstance(raw.get("has_phone"), bool) else None,
        "stock_quantity": to_int(g(attrs, "stock_quantity", 0, default=None)),
        "seller_reference": _text(g(attrs, "custom_ref", 0, default=None)),
        "images": _images(raw),
        "videos": _videos(raw),
        "attributes": _attributes(raw),
        "highlights": _highlights(raw),
        "location": _ad_location(raw),
        "seller": _ad_seller(raw, attrs),
        "shipping": _shipping(raw, attrs),
        "promotion": _promotion(raw),
        "published_at": wall_clock_utc(raw.get("first_publication_date"), SITE_ZONE),
        "updated_at": wall_clock_utc(raw.get("index_date"), SITE_ZONE),
        "expires_at": wall_clock_utc(raw.get("expiration_date"), SITE_ZONE),
    }


def parse_ads(payload):
    return [ad for ad in (parse_ad(raw) for raw in as_list(as_dict(payload).get("ads"))) if ad and ad["id"]]


def _promoted(payload):
    """The pros' paid ads the site shows in a strip above some searches
    (cars, real estate): close to the search, not part of its count."""
    out, seen = [], {str(as_dict(ad).get("list_id")) for ad in as_list(payload.get("ads"))}
    for widget in as_list(payload.get("ads_widget")):
        for ad in parse_ads(widget):
            if str(ad["id"]) not in seen:       # the strip repeats ads of the page itself
                seen.add(str(ad["id"]))
                out.append(ad)
    return out


def parse_search(payload, page, limit):
    """A search answer -> {"ads", "promoted_ads", "pagination",
    "private_count", "pro_count", "suggested_category_id"}. A page past the
    site's depth is answered with no rows and no total: an empty page."""
    payload = as_dict(payload)
    ads = parse_ads(payload)
    total = to_int(payload.get("total")) or 0
    if ads or page == 1:
        pages = to_int(payload.get("max_pages")) or (-(-total // limit) if total else 0)
        pagination = {"page": page, "items_per_page": limit, "total_pages": pages, "total_count": total}
    else:
        pagination = {"page": page, "items_per_page": limit, "total_pages": None, "total_count": None, "has_next": False}
    counted = bool(to_int(payload.get("total_all")))
    return {
        "private_count": to_int(payload.get("total_private")) if counted else None,
        "pro_count": to_int(payload.get("total_pro")) if counted else None,
        "suggested_category_id": _text(payload.get("suggested_category_id")),
        "ads": ads,
        "promoted_ads": _promoted(payload),
        "pagination": pagination,
    }


def parse_bulk(payload, wanted):
    """The by-id answer against the ids asked: the ads in the order asked,
    and the ids the site did not return."""
    by_id = {str(ad["id"]): ad for ad in parse_ads(payload)}
    return {"ads": [by_id[i] for i in wanted if i in by_id], "not_found": [int(i) for i in wanted if i not in by_id]}


# ---- sellers -------------------------------------------------------------------------

def _picture(raw):
    picture = as_dict(raw)
    return picture.get("extra_large_url") or picture.get("large_url") or picture.get("medium_url") or picture.get("small_url") or None


def _score_list(scores):
    return [{"name": _snake(name), "rating": _stars(score)} for name, score in as_dict(scores).items()]


def parse_seller_card(raw, user_id=None):
    """The seller card -> the seller's own fields (company, store,
    followers and website are added by parse_seller)."""
    raw = as_dict(raw)
    feedback = as_dict(raw.get("feedback"))
    reply = as_dict(raw.get("reply"))
    presence = as_dict(raw.get("presence"))
    badges = [b for b in (_snake(as_dict(b).get("name")) for b in as_list(raw.get("badges"))) if b]
    uid = _text(raw.get("user_id")) or user_id
    return {
        "id": uid,
        "name": _text(raw.get("name")),
        "link": refs.profile_link(uid),
        "type": _text(raw.get("account_type")),
        "description": multiline(raw.get("description")) if isinstance(raw.get("description"), str) else None,
        "location": _text(raw.get("location")),
        "picture": _picture(raw.get("profile_picture")),
        "has_default_picture": g(raw, "profile_picture", "is_default", default=None),
        "registered_date": iso_day(raw.get("registered_at")),
        "ads_count": to_int(raw.get("total_ads")),
        "account_id": _text(str(raw["store_id"])) if raw.get("store_id") else None,
        "rating": _stars(feedback.get("overall_score")),
        "reviews_count": to_int(feedback.get("received_count")) or 0,
        "rating_categories": _score_list(feedback.get("category_scores")),
        "is_phone_verified": "verified_phone_number" in badges,
        "badges": badges,
        "reply": {
            "rate_percent": to_int(reply.get("rate")),
            "time_minutes": to_int(reply.get("in_minutes")) or None,
            "rate_text": _text(reply.get("rate_text")),
            "time_text": _text(reply.get("text")),
        },
        "presence": {
            "status": (_text(presence.get("status")) or "").lower() or None,
            "last_active_at": iso_utc(presence.get("last_activity")),
            "text": _text(presence.get("presence_text")),
        },
    }


def parse_company(raw):
    """A pro's company record; None for a private seller."""
    if not isinstance(raw, dict) or not raw:
        return None
    address = as_dict(raw.get("address"))
    return {
        "name": _text(raw.get("companyName")),
        "siren": _text(raw.get("siren")),
        "siret": _text(raw.get("siret")),
        "activity_sector": _text(raw.get("activitySector")),
        "activity_sector_id": to_int(raw.get("activitySectorID")),
        "category_id": _text(str(raw["categoryId"])) if raw.get("categoryId") else None,
        "address": _text(address.get("address")),
        "zipcode": _text(address.get("zipcode")),
        "city": _text(address.get("city")),
        "is_dsa_self_certified": raw.get("dsa_self_certified") if isinstance(raw.get("dsa_self_certified"), bool) else None,
    }


def _store_picture(raw):
    picture = as_dict(raw)
    return picture.get("large") or picture.get("small") or picture.get("thumbnail") or None


def _website(value):
    """The store's own website as a link ("simsize.fr" -> "http://simsize.fr");
    a link back to leboncoin is not a website of its own."""
    value = _text(value)
    if not value or " " in value or "." not in value:
        return None
    link = value if re.match(r"^https?://", value, re.I) else "http://" + value.lstrip("/")
    host = re.sub(r"^https?://", "", link, flags=re.I).split("/")[0].lower()
    if host == "leboncoin.fr" or host.endswith(".leboncoin.fr"):
        return None
    return link


def _external_rating(raw):
    """The rating a store page shows from another site (Google Maps), with
    the few reviews the page quotes; None when the page shows none."""
    if not isinstance(raw, dict) or not raw:
        return None
    reviews = []
    for review in as_list(raw.get("reviews")):
        if isinstance(review, dict):
            reviews.append({"author": _text(review.get("author_name")), "rating": num(review.get("rating_value")),
                            "text": multiline(review.get("text")) if isinstance(review.get("text"), str) else None,
                            "date": iso_utc(review.get("review_time"))})
    return {
        "source": _text(raw.get("source_display")) or _text(raw.get("source")),
        "rating": num(raw.get("rating_value")),
        "reviews_count": to_int(raw.get("user_ratings_total")),
        "link": _text(raw.get("url")),
        "retrieved_at": iso_utc(_seconds(raw.get("retrieval_time"))),
        "reviews": reviews,
    }


def _seconds(stamp):
    """An ISO time with nanoseconds ('…:32.261971017Z') cut to seconds."""
    return re.sub(r"\.\d+", "", stamp) if isinstance(stamp, str) else None


def _activity_zone(raw):
    """Where a pro says it works: a radius around a place; None when not given."""
    if not isinstance(raw, dict) or not raw:
        return None
    place = as_dict(raw.get("location"))
    radius = num(raw.get("radius"))
    return {
        "label": _text(place.get("label")),
        "city": _text(place.get("city")),
        "zipcode": _text(place.get("zipcode")),
        "district": _text(place.get("district")),
        "radius_km": amount(radius / 1000) if radius is not None else None,
        "latitude": num(place.get("lat")),
        "longitude": num(place.get("lng")),
    }


def parse_store(raw):
    """A pro's store page; None when there is none."""
    if not isinstance(raw, dict) or not raw.get("online_store_id"):
        return None
    owner = as_dict(raw.get("owner"))
    location = as_dict(raw.get("location"))
    media = as_dict(raw.get("media"))
    team = []
    portraits = as_list(raw.get("team_member_portraits"))
    for index, member in enumerate(as_list(raw.get("team_members"))):
        if isinstance(member, dict) and (member.get("name") or member.get("position")):
            team.append({"name": _text(member.get("name")), "position": _text(member.get("position")),
                         "picture": _store_picture(portraits[index]) if index < len(portraits) else None})
    store_id = to_int(raw.get("online_store_id"))
    return {
        "id": store_id,
        "name": _text(raw.get("online_store_name")),
        "link": refs.store_link(store_id),
        "slogan": _text(raw.get("slogan")),
        "description": multiline(raw.get("description")) if isinstance(raw.get("description"), str) else None,
        "opening_hours": multiline(raw.get("opening_hours")) if isinstance(raw.get("opening_hours"), str) else None,
        "website": _website(raw.get("website_url")),
        "active_since": iso_day(owner.get("activeSince")),
        "external_rating": _external_rating(raw.get("rating")),
        "siren": _text(owner.get("siren")),
        "siret": _text(owner.get("siret")),
        "activity_sector": _text(owner.get("activitySector")),
        "activity_sector_id": to_int(owner.get("activitySectorID")),
        "category_id": _text(str(owner["categoryId"])) if owner.get("categoryId") else None,
        "owner_id": _text(owner.get("userId")),
        "address": {
            "label": _text(location.get("label")),
            "street": _text(raw.get("address")) or _text(location.get("address")),
            "city": _text(location.get("city")) or _text(raw.get("city")),
            "zipcode": _text(location.get("zipcode")) or _text(raw.get("zipcode")),
            "district": _text(location.get("district")),
            "department": {"id": _text(location.get("department")), "name": _text(location.get("dpt_label"))},
            "region": {"id": _text(location.get("region")), "name": _text(location.get("region_label"))},
            "country": _text(location.get("country")),
            "latitude": num(location.get("lat")),
            "longitude": num(location.get("lng")),
            "is_hidden": raw.get("hide_address") if isinstance(raw.get("hide_address"), bool) else None,
        },
        "has_phone": (not raw["hide_phone"]) if isinstance(raw.get("hide_phone"), bool) else None,
        "has_contact_form": (not raw["hide_contact_form"]) if isinstance(raw.get("hide_contact_form"), bool) else None,
        "logo": _store_picture(raw.get("logo")),
        "cover": _store_picture(raw.get("cover")),
        "pictures": [p for p in (_store_picture(p) for p in as_list(raw.get("pictures"))) if p],
        "services": [s for s in (_text(as_dict(p).get("display_name")) for p in as_list(raw.get("prestations"))) if s],
        "activity_zone": _activity_zone(raw.get("activity_zone")),
        "sold_properties_count": to_int(g(raw, "sold_properties", "total", default=None)) if isinstance(raw.get("sold_properties"), dict) else None,
        "team": team,
        "promotion": ({"title": _text(media.get("title")), "link": _text(media.get("link_url")),
                       "image": _store_picture(raw.get("media_image_url"))}
                      if _text(media.get("title")) or _text(media.get("link_url")) else None),
    }


def parse_seller(card, user_id=None, company=None, store=None, followers=None):
    """The seller's answer: the card, then the pro's company record and
    store page, the store's website on top where the contact lookup reads it."""
    seller = parse_seller_card(card, user_id)
    parsed_store = parse_store(store)
    head = {k: seller[k] for k in ("id", "name", "link", "type", "description", "location")}
    rest = {k: v for k, v in seller.items() if k not in head}
    return {
        **head,
        "website": parsed_store["website"] if parsed_store else None,
        **{k: rest[k] for k in ("picture", "has_default_picture", "registered_date", "ads_count")},
        "followers_count": to_int(as_dict(followers).get("count")),
        **{k: v for k, v in rest.items() if k not in ("picture", "has_default_picture", "registered_date", "ads_count")},
        "company": parse_company(company),
        "store": parsed_store,
    }


# ---- reviews -------------------------------------------------------------------------

def parse_reputation(raw):
    raw = as_dict(raw)
    return {
        "rating": _stars(raw.get("overallScore")),
        "reviews_count": to_int(raw.get("receivedCount")) or 0,
        "written_reviews_count": to_int(raw.get("memberFeedbackWithTextReviewCount")),
        "as_seller_count": to_int(raw.get("sellerFeedbackCount")),
        "as_buyer_count": to_int(raw.get("buyerFeedbackCount")),
        "member_reviews_count": to_int(g(raw, "sourceCounts", "MEMBER", default=None)),
        "automatic_reviews_count": to_int(g(raw, "sourceCounts", "AUTOMATIC", default=None)),
        "member_rating": _stars(g(raw, "sourceScores", "MEMBER", default=None)),
        "rating_categories": _score_list(raw.get("categoryScores")),
    }


def parse_review(raw):
    raw = as_dict(raw)
    feedback = as_dict(raw.get("feedback"))
    item = as_dict(feedback.get("item"))
    reply = feedback.get("reply")
    reviewer_id = _user_id(feedback.get("ownerId"))
    return {
        "id": to_int(feedback.get("feedbackId")) or None,
        "rating": _stars(feedback.get("score")),
        "text": multiline(feedback.get("textReview")) if isinstance(feedback.get("textReview"), str) else None,
        "date": iso_utc(feedback.get("givenAt")),
        "is_automatic": feedback.get("isAutomaticReview") if isinstance(feedback.get("isAutomaticReview"), bool) else None,
        "source": (_text(feedback.get("source")) or "").lower() or None,
        "reviewer_role": (_text(raw.get("role")) or "").lower() or None,
        "reply": (multiline(as_dict(reply).get("text") if isinstance(reply, dict) else reply)
                  if isinstance(reply, (dict, str)) else None),
        "item": {"title": _text(item.get("title")), "image": item.get("pictureUrl") or None},
        "reviewer": {
            "id": reviewer_id,
            "name": _text(raw.get("name")),
            "link": refs.profile_link(reviewer_id) if refs.USER_ID_RE.match(reviewer_id or "") else None,
            "picture": raw.get("avatarUrl") or None,
            "is_professional": raw.get("isProfessional") if isinstance(raw.get("isProfessional"), bool) else None,
            "is_verified": raw.get("verified") if isinstance(raw.get("verified"), bool) else None,
            "rating": _stars(raw.get("overallScore")),
            "reviews_count": to_int(raw.get("numberOfReceivedFeedbacks")),
        },
    }


def parse_reviews(payload, page, limit):
    """A reviews answer -> {"summary", "reviews", "pagination"}; None (a
    user the review service does not know) reads as no review."""
    payload = as_dict(payload)
    meta = as_dict(payload.get("pagination"))
    total = to_int(meta.get("totalCount")) or 0
    return {
        "summary": parse_reputation(payload.get("reputation")),
        "reviews": [parse_review(r) for r in as_list(payload.get("result")) if isinstance(r, dict)],
        "pagination": {"page": page, "items_per_page": limit, "total_count": total,
                       "total_pages": -(-total // limit) if total else 0},
    }


# ---- suggestions and locations ---------------------------------------------------------

def parse_suggestions(payload, categories=None):
    """Keyword suggestions, each with the category the site would search it
    in (None: every category). `categories` is the reference's by-id map."""
    out = []
    for item in as_list(as_dict(payload).get("suggestions")):
        if not isinstance(item, dict) or not _text(item.get("text")):
            continue
        cat_id = to_int(item.get("cat_id"))
        category = None
        if cat_id is not None and cat_id > 0:
            known = as_dict(categories).get(str(cat_id)) or {}
            category = {"id": str(cat_id), "name": known.get("name"), "slug": known.get("slug")}
        row = {"text": _text(item["text"]), "category": category}
        if row not in out:
            out.append(row)
    return out


def parse_location(raw):
    """One of the site's location objects -> a row whose `value` selects it
    again in the `location` param of a search."""
    raw = as_dict(raw)
    area = as_dict(raw.get("area"))
    return {
        "value": refs.location_token(raw),
        "type": _text(raw.get("locationType")),
        "label": _text(raw.get("label")),
        "city": _text(raw.get("city")),
        "zipcode": _text(raw.get("zipcode")),
        "place": _text(raw.get("place")),
        "department_id": _text(raw.get("department_id")),
        "region_id": _text(raw.get("region_id")),
        "country": _text(raw.get("country_id")),
        "latitude": num(area.get("lat")),
        "longitude": num(area.get("lng")),
        "default_radius_meters": to_int(area.get("default_radius")),
    }


def parse_locations(payload):
    return [row for row in (parse_location(r) for r in as_list(payload) if isinstance(r, dict)) if row["value"]]


# ---- reference data: categories and filters --------------------------------------------

_AD_TYPE_NAMES = {"sell": "offer", "let": "offer", "buy": "demand", "rent": "demand"}


def _category(raw, parent=None):
    cat_id = _text(str(raw.get("catId"))) if raw.get("catId") is not None else None
    slug = _text(raw.get("deeplink"))
    mirror = as_dict(raw.get("filters")) if raw.get("type") == "mirror" else None
    ad_types = []
    for key, described in as_dict(raw.get("ad_types")).items():
        ad_types.append({"type": _AD_TYPE_NAMES.get(key, key), "label": _text(as_dict(described).get("label")),
                         "description": _text(as_dict(described).get("description"))})
    return {
        "id": cat_id,
        "name": _text(raw.get("name")) or _text(raw.get("label")),
        "slug": slug,
        "link": refs.category_link(slug) if not raw.get("url") else None,
        "external_link": _text(raw.get("url")),
        "parent_id": _text(str(raw.get("categoryParentId"))) if raw.get("categoryParentId") is not None else parent,
        "same_as": ({"category_id": _text(g(mirror, "category", "id", default=None)),
                     "filters": [{"key": k, "value": "|".join(str(x) for x in as_list(v))} for k, v in as_dict(mirror.get("enums")).items()]}
                    if mirror else None),
        "ad_types": ad_types,
    }


def _feature_values(feature):
    values = as_dict(feature.get("values"))
    kind = values.get("type")
    rows = []
    if kind == "simple":
        for item in as_list(values.get("simpleData")):
            if isinstance(item, dict) and item.get("value") not in (None, ""):
                rows.append({"value": str(item["value"]), "label": _text(item.get("label")), "group": None})
    elif kind == "grouped":
        for group in as_list(values.get("groupedData")):
            for item in as_list(as_dict(group).get("list")):
                if isinstance(item, dict) and item.get("value") not in (None, ""):
                    rows.append({"value": str(item["value"]), "label": _text(item.get("label")), "group": _text(as_dict(group).get("header"))})
    return rows


def _feature(name, raw):
    values = _feature_values(raw)
    source = as_dict(raw.get("values"))
    is_range = raw.get("apiType") == "range"
    depends = [as_dict(p).get("param") for p in as_list(g(source, "endpoint", "params", default=None))] if source.get("type") == "endpoint" else []
    return {
        "feature": name,
        "key": _text(raw.get("param")) or name,
        "name": _text(raw.get("label")),
        "type": "range" if is_range else "choice",
        "is_multiple": (raw.get("format") == "multiple") if not is_range else None,
        "unit": _text(raw.get("unit")),
        "description": _text(raw.get("description")) or _text(raw.get("fullDescription")),
        "is_date": raw.get("format") == "date",
        "open": source.get("type") == "endpoint",       # values come from a call of their own: any value is passed on
        "depends_on": [d for d in depends if d],
        "values": values,
    }


def parse_reference(fdata, fforms):
    """The site's reference data -> what the endpoints look things up in:

      categories   the category tree (categories/list)
      by_id        {category id: its record, flat}
      by_slug      {slug or lower-case name: category id}
      features     {feature name: its filter record}
      params       {filter key: {"type", "values": {lower-case token: token},
                    "labels": {lower-case label: token}, "open": True when
                    any value is accepted, "is_date"}}: several features can share
                    one key (every car brand has its own model list under
                    `u_car_model`)
      forms        {category id: the entries of its filter form}
      multi        {name: {parent value: entries}}: the filters that depend
                    on another one's value
    """
    fdata, fforms = as_dict(fdata), as_dict(fforms)
    tree, by_id, by_slug = [], {}, {}
    for top in as_list(fdata.get("categories")):
        if not isinstance(top, dict) or str(top.get("catId")) == "0":
            continue
        node = _category(top)
        node["subcategories"] = []
        by_id[node["id"]] = {k: v for k, v in node.items() if k != "subcategories"}
        for sub in as_list(top.get("subcategories")):
            if isinstance(sub, dict):
                child = _category(sub, node["id"])
                node["subcategories"].append(child)
                by_id[child["id"]] = child
        tree.append(node)
    # every slug first: a group's name ("Animaux", id 75) must not take the
    # slug of the category under it (`animaux`, id 28, as in /c/animaux)
    for key in ("slug", "name"):
        for cat_id, record in by_id.items():
            if record[key]:
                by_slug.setdefault(record[key].casefold(), cat_id)
    features, params = {}, {}
    for name, raw in as_dict(fdata.get("features")).items():
        if not isinstance(raw, dict):
            continue
        feature = _feature(name, raw)
        features[name] = feature
        entry = params.setdefault(feature["key"], {"type": feature["type"], "values": {}, "labels": {}, "open": False,
                                                   "is_date": feature["is_date"]})
        if feature["open"] or (feature["type"] == "choice" and not feature["values"]):
            entry["open"] = True
        for row in feature["values"]:
            entry["values"].setdefault(row["value"].casefold(), row["value"])
            if row["label"]:
                entry["labels"].setdefault(row["label"].casefold(), row["value"])
    multi = as_dict(fforms.get("multi"))
    forms = as_dict(g(multi, "categoryFields", "offer", default=None))
    return {"categories": tree, "by_id": by_id, "by_slug": by_slug, "features": features, "params": params,
            "forms": forms, "multi": {k: v for k, v in multi.items() if k not in ("categoryFields", "funnel_categoryFields")}}


def _public_filter(feature, depends_on=None):
    return {
        "key": feature["key"],
        "name": feature["name"],
        "type": feature["type"],
        "is_multiple": feature["is_multiple"],
        "unit": feature["unit"],
        "description": feature["description"],
        "depends_on": depends_on or (feature["depends_on"][0] if feature["depends_on"] else None),
        "values": feature["values"] or None,
    }


def parse_category_filters(reference, category_id, chosen=None):
    """The filters of a category's search form, in the site's order. A
    filter that depends on another one's value (a car's model on its brand)
    lists its values once that value is in `chosen` ({key: [tokens]});
    until then it is named with `depends_on` and no values."""
    chosen = {k: [str(v).casefold() for v in vs] for k, vs in (chosen or {}).items()}
    features, multi = reference["features"], reference["multi"]
    out, seen = [], set()

    def add(row):
        mark = (row["key"], tuple(v["value"] for v in row["values"] or []))
        if mark not in seen:
            seen.add(mark)
            out.append(row)

    def walk(entries, depends_on=None):
        for entry in as_list(entries):
            if not isinstance(entry, dict):
                continue
            name = entry.get("name")
            if entry.get("type") == "feature" and name in features:
                add(_public_filter(features[name], depends_on))
            elif entry.get("type") == "multi" and isinstance(multi.get(name), dict):
                parents = [p for p in as_list(entry.get("conditionalFeatures")) if isinstance(p, str)]
                parent_key = features[parents[0]]["key"] if parents and parents[0] in features else (parents[0] if parents else None)
                branches = multi[name]
                picked = [value for value in branches if value.casefold() in chosen.get(parent_key, [])]
                if picked:
                    for value in picked:
                        walk(branches[value], parent_key)
                else:
                    keys = []
                    for branch in branches.values():
                        for sub in as_list(branch):
                            feature = features.get(as_dict(sub).get("name"))
                            if feature and feature["key"] not in keys:
                                keys.append(feature["key"])
                    for key in keys:
                        named = next(f for f in features.values() if f["key"] == key)
                        add({"key": key, "name": named["name"], "type": named["type"], "is_multiple": named["is_multiple"],
                             "unit": named["unit"], "description": named["description"], "depends_on": parent_key, "values": None})

    walk(reference["forms"].get(str(category_id)))
    return out
