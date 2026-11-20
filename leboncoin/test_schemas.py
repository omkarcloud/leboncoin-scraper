"""Offline tests for the /leboncoin/* request schemas and the reference
resolvers.

    python -m pytest leboncoin/test_schemas.py -q
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from leboncoin import refs, schemas  # noqa: E402
from schema_fields import load_query  # noqa: E402

AD_LINK = "https://www.leboncoin.fr/ad/telephones_objets_connectes/3091399005"
USER = "031c778f-f4bd-4969-98a8-179c1f4efd2f"
SEARCH_LINK = ("https://www.leboncoin.fr/recherche?category=2&u_car_brand=PEUGEOT&mileage=min-100000&fuel=1,2"
               "&owner_type=pro&regdate=2018-max&locations=d_69,Lyon__45.76053_4.83772_10000&sort=time&order=desc&page=2")


def errors_of(schema_cls, query):
    data, error = load_query(schema_cls, query)
    assert data is None, data
    return error["errors"]


# ---- refs: ads -------------------------------------------------------------------------

@pytest.mark.parametrize("value, expected", [
    ("3091399005", "3091399005"),
    (" 3091399005 ", "3091399005"),
    ("1780433818", "1780433818"),
    (AD_LINK, "3091399005"),
    (AD_LINK + "?utm_source=x#top", "3091399005"),
    ("www.leboncoin.fr/ad/voitures/3307889240", "3307889240"),
    ("//www.leboncoin.fr/ad/voitures/3307889240/", "3307889240"),
    ("/ad/voitures/3307889240", "3307889240"),
    ("https://www.leboncoin.fr/voitures/1780433818.htm", "1780433818"),
    ("https://www.leboncoin.fr/vi/1780433818.htm", "1780433818"),
])
def test_resolve_ad(value, expected):
    assert refs.resolve_ad(value) == expected


@pytest.mark.parametrize("value", [
    "", "abc", "12", "3091399005x", "https://example.com/ad/voitures/3307889240",
    "https://www.leboncoin.fr/recherche?text=velo", "https://www.leboncoin.fr/profile/" + USER + "/offers",
    "https://www.leboncoin.fr/", "https://www.leboncoin.fr/c/voitures",
    "https://www.leboncoin.fr/boutique/338302",                    # a store link (this API's own store.link), not an ad
])
def test_resolve_ad_rejects(value):
    with pytest.raises(ValueError):
        refs.resolve_ad(value)


def test_resolve_ads():
    assert refs.resolve_ads(f"3091399005, {AD_LINK} ,3304725293,") == ["3091399005", "3304725293"]
    with pytest.raises(ValueError) as error:
        refs.resolve_ads(",".join(str(3000000000 + n) for n in range(101)))
    assert "At most 100" in str(error.value)
    assert len(refs.resolve_ads(",".join(str(3000000000 + n) for n in range(100)))) == 100
    for bad in ("", " , ", "3091399005,nope"):
        with pytest.raises(ValueError):
            refs.resolve_ads(bad)


# ---- refs: sellers ---------------------------------------------------------------------

@pytest.mark.parametrize("value, expected", [
    (USER, USER),
    (USER.upper(), USER),
    (f"https://www.leboncoin.fr/profile/{USER}/offers", USER),
    (f"https://www.leboncoin.fr/profile/{USER}", USER),
    (f"www.leboncoin.fr/profile/{USER}/feedbacks?x=1", USER),
    ("https://www.leboncoin.fr/boutique/338302/simsize_mobile.htm", "boutique:338302"),
    ("https://www.leboncoin.fr/boutique/338302", "boutique:338302"),
    ("338302", "boutique:338302"),
    ("boutique:338302", "boutique:338302"),
])
def test_resolve_seller(value, expected):
    assert refs.resolve_seller(value) == expected


@pytest.mark.parametrize("value", ["", "SIMSIZE", "031c778f-f4bd", AD_LINK, "https://example.com/profile/" + USER,
                                   "https://www.leboncoin.fr/profile/not-a-uuid/offers"])
def test_resolve_seller_rejects(value):
    with pytest.raises(ValueError):
        refs.resolve_seller(value)


def test_store_id_of():
    assert refs.store_id_of("boutique:338302") == 338302 and refs.store_id_of(USER) is None


# ---- refs: categories, locations, filters ----------------------------------------------

@pytest.mark.parametrize("value, expected", [
    ("2", "2"), ("voitures", "voitures"), ("Voitures", "Voitures"), ("_vehicules_", "_vehicules_"),
    ("https://www.leboncoin.fr/c/voitures", "voitures"),
    ("https://www.leboncoin.fr/c/voitures/u_car_brand:PEUGEOT", "voitures"),
    ("https://www.leboncoin.fr/recherche?category=9&text=x", "9"),
])
def test_resolve_category(value, expected):
    assert refs.resolve_category(value) == expected


@pytest.mark.parametrize("value", ["", "a/b", AD_LINK, "https://example.com/c/voitures", "x" * 81])
def test_resolve_category_rejects(value):
    with pytest.raises(ValueError):
        refs.resolve_category(value)


def test_resolve_location_forms():
    found = refs.resolve_location("Lyon; d_69; rn_22; 45.76,4.83; Lyon_69003__45.75898_4.86114_3774; "
                                  "p_Vallée du Rhône__44.42_4.88_5000; d_2A")
    assert found[0] == {"text": "Lyon"}
    assert found[1] == {"locationType": "department", "department_id": "69"}
    assert found[2] == {"locationType": "region_near", "region_id": "22"}
    # a bare point is matched by `radius` alone (the site ignores default_radius without a city name)
    assert found[3] == {"locationType": "city", "label": "45.76,4.83",
                        "area": {"lat": 45.76, "lng": 4.83, "radius": 10000}}
    assert refs.resolve_location("__45.76_4.83_5000")[0]["area"] == {"lat": 45.76, "lng": 4.83, "radius": 5000}
    assert found[4] == {"locationType": "city", "area": {"lat": 45.75898, "lng": 4.86114, "default_radius": 3774},
                        "zipcode": "69003", "city": "Lyon", "label": "Lyon (69003)"}
    assert found[5] == {"locationType": "place", "place": "Vallée du Rhône", "label": "Vallée du Rhône",
                        "area": {"lat": 44.42, "lng": 4.88, "default_radius": 5000}}
    assert found[6] == {"locationType": "department", "department_id": "2A"}
    # the site's own link form: a comma between locations, the radius after the default radius
    link = refs.resolve_location("Lyon__45.76053_4.83772_10000_30000,d_69", separator=",")
    assert link[0]["area"] == {"lat": 45.76053, "lng": 4.83772, "default_radius": 10000, "radius": 30000}
    assert link[1] == {"locationType": "department", "department_id": "69"}
    assert refs.resolve_location("33000") == [{"text": "33000"}]
    assert refs.resolve_location("Lyon; lyon ;Lyon") == [{"text": "Lyon"}, {"text": "lyon"}]


@pytest.mark.parametrize("value", ["", " ; ", "95.0,4.8", "Lyon__nonsense", "x" * 121,
                                   ";".join(f"d_{n}" for n in range(11))])
def test_resolve_location_rejects(value):
    with pytest.raises(ValueError):
        refs.resolve_location(value)


def test_resolve_filters():
    assert refs.resolve_filters("fuel:1|2, Mileage:min-100000,regdate:2018-max") == [
        ["fuel", "1|2"], ["mileage", "min-100000"], ["regdate", "2018-max"]]
    for bad in ("", "fuel", "fuel:", ":1", "fuel:1,fuel:2", "Fu el:1", ",".join(f"k{n}:1" for n in range(21))):
        with pytest.raises(ValueError):
            refs.resolve_filters(bad)


# ---- refs: a search link ---------------------------------------------------------------

def test_search_link_is_read_into_the_apis_own_params():
    link = refs.resolve_query(SEARCH_LINK)["link"]
    assert link == {
        "category": "2", "seller_type": "pro", "sort": "newest", "page": 2,
        "location": [{"locationType": "department", "department_id": "69"},
                     {"locationType": "city", "area": {"lat": 45.76053, "lng": 4.83772, "default_radius": 10000},
                      "city": "Lyon", "label": "Lyon"}],
        "filters": [["u_car_brand", "PEUGEOT"], ["mileage", "min-100000"], ["fuel", "1|2"], ["regdate", "2018-max"]],
    }


def test_search_link_keywords_title_only_delivery_and_sort():
    link = refs.resolve_query("https://www.leboncoin.fr/recherche?text=velo%20enfant&locations=r_12&shippable=1"
                              "&search_in=subject&sort=price&order=asc&kst=k")["link"]
    assert link == {"query": "velo enfant", "location": [{"locationType": "region", "region_id": "12"}],
                    "include_delivery": True, "title_only": True, "sort": "price_asc"}
    assert refs.resolve_query("https://www.leboncoin.fr/recherche?text=x&sort=time")["link"]["sort"] == "newest"
    assert "sort" not in refs.resolve_query("https://www.leboncoin.fr/recherche?text=x")["link"]


def test_category_page_link():
    assert refs.resolve_query("https://www.leboncoin.fr/c/voitures/u_car_brand:PEUGEOT")["link"] == {
        "category": "voitures", "filters": [["u_car_brand", "PEUGEOT"]]}


def test_keywords_stay_keywords():
    assert refs.resolve_query("  iphone   15 ") == {"text": "iphone 15"}
    with pytest.raises(ValueError):
        refs.resolve_query("x" * 201)


@pytest.mark.parametrize("value, fragment", [
    (AD_LINK, "ad link"),
    (f"https://www.leboncoin.fr/profile/{USER}/offers", "seller link"),
    ("https://www.leboncoin.fr/", "search link"),
    ("https://example.com/recherche?text=x", "leboncoin.fr link"),
    ("https://www.leboncoin.fr/recherche?text=x&sort=weird", "sort"),
])
def test_search_link_rejects(value, fragment):
    with pytest.raises(ValueError) as error:
        refs.resolve_query(value)
    assert fragment in str(error.value)


# ---- schemas ---------------------------------------------------------------------------

def test_ads_search_defaults():
    data, error = load_query(schemas.AdsSearchSchema, {})
    assert error is None
    assert data == {"query": None, "category": None, "location": None, "radius": None, "price_min": None,
                    "price_max": None, "seller_type": None, "ad_type": None, "sort": None, "title_only": None,
                    "include_delivery": None, "urgent_only": None, "free_only": None, "filters": None,
                    "page": 1, "limit": 35}


def test_ads_search_accepts():
    data, error = load_query(schemas.AdsSearchSchema, {
        "query": "iphone 15", "category": "17", "location": "Lyon;d_69", "radius": "30", "price_min": "100",
        "price_max": "500", "seller_type": "PRO", "ad_type": "demand", "sort": "price_asc", "title_only": "true",
        "include_delivery": "1", "urgent_only": "yes", "free_only": "false", "filters": "fuel:1", "page": "3",
        "limit": "100"})
    assert error is None
    assert data["query"] == {"text": "iphone 15"} and data["category"] == "17"
    assert data["location"] == [{"text": "Lyon"}, {"locationType": "department", "department_id": "69"}]
    assert (data["radius"], data["price_min"], data["price_max"]) == (30, 100, 500)
    assert (data["seller_type"], data["ad_type"], data["sort"]) == ("pro", "demand", "price_asc")
    assert (data["title_only"], data["include_delivery"], data["urgent_only"], data["free_only"]) == (True, True, True, False)
    assert data["filters"] == [["fuel", "1"]] and (data["page"], data["limit"]) == (3, 100)
    linked, error = load_query(schemas.AdsSearchSchema, {"query": SEARCH_LINK})
    assert error is None and linked["query"]["link"]["category"] == "2"


@pytest.mark.parametrize("query, field, fragment", [
    ({"limit": "101"}, "limit", "100"),
    ({"limit": "0"}, "limit", "1"),
    ({"page": "0"}, "page", "1"),
    ({"page": "3501"}, "page", "3500"),
    ({"radius": "201"}, "radius", "200"),
    ({"sort": "cheapest"}, "sort", "relevance, newest, oldest, price_asc, price_desc"),
    ({"seller_type": "shop"}, "seller_type", "private, pro"),
    ({"ad_type": "sell"}, "ad_type", "offer, demand"),
    ({"title_only": "maybe"}, "title_only", "true or false"),
    ({"filters": "fuel"}, "filters", "key:value"),
    ({"location": "95.0,4.8"}, "location", "Latitude"),
    ({"category": "a/b"}, "category", "category id"),
    ({"query": AD_LINK}, "query", "ad link"),
    ({"price_min": "-5"}, "price_min", "1"),
    ({"url": "https://www.leboncoin.fr/recherche"}, "url", "Unknown field"),
])
def test_ads_search_rejects(query, field, fragment):
    assert fragment in " ".join(errors_of(schemas.AdsSearchSchema, query)[field])


def test_ad_schemas():
    assert load_query(schemas.AdsDetailsSchema, {"ad": AD_LINK})[0] == {"ad": "3091399005"}
    assert "Missing data" in errors_of(schemas.AdsDetailsSchema, {})["ad"][0]
    assert "ad id" in errors_of(schemas.AdsDetailsSchema, {"ad": "nope"})["ad"][0]
    assert "Unknown field" in errors_of(schemas.AdsDetailsSchema, {"ad": "3091399005", "id": "1"})["id"][0]
    assert load_query(schemas.AdsBulkSchema, {"ads": f"3304725293,{AD_LINK}"})[0] == {"ads": ["3304725293", "3091399005"]}
    assert "At most 100" in errors_of(schemas.AdsBulkSchema, {"ads": ",".join(str(3000000000 + n) for n in range(101))})["ads"][0]
    assert load_query(schemas.AdsSimilarSchema, {"ad": "3091399005"})[0] == {"ad": "3091399005", "limit": 10}
    assert "limit" in errors_of(schemas.AdsSimilarSchema, {"ad": "3091399005", "limit": "101"})


def test_seller_schemas():
    assert load_query(schemas.SellersDetailsSchema, {"seller": USER.upper()})[0] == {"seller": USER}
    assert load_query(schemas.SellersAdsSchema, {"seller": "https://www.leboncoin.fr/boutique/338302"})[0] == {
        "seller": "boutique:338302", "page": 1, "limit": 35}
    assert load_query(schemas.SellersReviewsSchema, {"seller": USER})[0] == {"seller": USER, "page": 1, "limit": 20}
    assert load_query(schemas.SellersReviewsSchema, {"seller": USER, "limit": "300"})[0]["limit"] == 300
    assert "limit" in errors_of(schemas.SellersReviewsSchema, {"seller": USER, "limit": "301"})
    assert "user id" in errors_of(schemas.SellersDetailsSchema, {"seller": "SIMSIZE"})["seller"][0]
    assert "Missing data" in errors_of(schemas.SellersAdsSchema, {})["seller"][0]


def test_lookup_schemas():
    assert load_query(schemas.SearchSuggestionsSchema, {"query": " iphone  15 "})[0] == {"query": "iphone 15"}
    assert "query" in errors_of(schemas.SearchSuggestionsSchema, {"query": "x" * 101})
    assert load_query(schemas.LocationsSearchSchema, {"query": "lyon"})[0] == {"query": "lyon"}
    assert "Missing data" in errors_of(schemas.LocationsSearchSchema, {})["query"][0]
    assert load_query(schemas.CategoriesListSchema, {})[0] == {}
    assert "Unknown field" in errors_of(schemas.CategoriesListSchema, {"category": "2"})["category"][0]
    assert load_query(schemas.CategoriesFiltersSchema, {"category": "voitures", "filters": "u_car_brand:PEUGEOT"})[0] == {
        "category": "voitures", "filters": [["u_car_brand", "PEUGEOT"]]}
    assert "Missing data" in errors_of(schemas.CategoriesFiltersSchema, {})["category"][0]


def test_every_field_says_what_it_takes():
    for name in dir(schemas):
        cls = getattr(schemas, name)
        if isinstance(cls, type) and name.endswith("Schema") and not name.startswith("_") and name != "BaseSchema":
            for field_name, field in cls().fields.items():
                assert field.metadata.get("description"), f"{name}.{field_name} has no description"


# ---- empty params (a form that sends every field) --------------------------------------

VALID = {"ad": "3091399005", "ads": "3091399005", "seller": USER, "query": "velo", "category": "2"}
ALL = [schemas.AdsSearchSchema, schemas.AdsDetailsSchema, schemas.AdsBulkSchema, schemas.AdsSimilarSchema,
       schemas.SellersDetailsSchema, schemas.SellersAdsSchema, schemas.SellersReviewsSchema,
       schemas.SearchSuggestionsSchema, schemas.LocationsSearchSchema, schemas.CategoriesListSchema,
       schemas.CategoriesFiltersSchema]


@pytest.mark.parametrize("schema_cls", ALL, ids=lambda c: c.__name__)
def test_an_empty_optional_param_is_the_absent_param(schema_cls):
    fields = {field.data_key or name: field for name, field in schema_cls().fields.items()}
    base = {key: VALID[key] for key, field in fields.items() if field.required}
    expected, error = load_query(schema_cls, base)
    assert error is None
    for key, field in fields.items():
        data, error = load_query(schema_cls, dict(base, **{key: ""}))      # raises (= a 500) on a crash
        if field.required:
            assert data is None and key in error["errors"]
        else:
            assert error is None and data == expected
