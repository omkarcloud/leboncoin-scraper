"""Offline tests for leboncoin/parsers.py and leboncoin/queries.py against
the raw captures in fixtures/ (taken 2026-11-20, untrimmed).

    python -m pytest leboncoin/test_parsers.py -q
"""
import gzip
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from leboncoin import parsers, queries  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def load(name):
    path = os.path.join(FIXTURES, name)
    opener = gzip.open if name.endswith(".gz") else open
    with opener(path, "rt", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def reference():
    return parsers.parse_reference(load("fdata.json.gz"), load("fforms.json"))


def attribute(ad, key):
    return next(a for a in ad["attributes"] if a["key"] == key)


def no_empty_strings(value, path="$"):
    """Every missing value is null, never '' (the response rules)."""
    if isinstance(value, dict):
        for key, item in value.items():
            no_empty_strings(item, f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            no_empty_strings(item, f"{path}[{index}]")
    else:
        assert value != "", path


# ---- ads -----------------------------------------------------------------------------

def test_search_page():
    found = parsers.parse_search(load("search_iphone_15.json"), 1, 5)
    assert found["pagination"] == {"page": 1, "items_per_page": 5, "total_pages": 700, "total_count": 34845}
    assert (found["private_count"], found["pro_count"], found["suggested_category_id"]) == (32909, 1936, "17")
    assert len(found["ads"]) == 5 and found["promoted_ads"] == []
    ad = found["ads"][0]
    assert list(ad)[:6] == ["id", "title", "link", "status", "ad_type", "description"]
    assert ad["id"] == 3304725293 and ad["title"] == "IPhone 15 Pro"
    assert ad["link"] == "https://www.leboncoin.fr/ad/telephones_objets_connectes/3304725293"
    assert ad["category"] == {"id": "17", "name": "Téléphones & Objets connectés", "slug": "telephones_objets_connectes"}
    assert ad["status"] == "active" and ad["ad_type"] == "offer" and ad["has_phone"] is False
    assert ad["description"].startswith("Je mets en vente mon iPhone 15 Pro")
    no_empty_strings(found)


def test_price_is_euros_from_cents_and_fees_too():
    ad = parsers.parse_search(load("search_iphone_15.json"), 1, 5)["ads"][0]
    # raw: price [480], price_cents 48000, buyer_fee {"amount": 199}
    assert ad["price"] == {"amount": 480, "currency": "EUR", "previous_amount": None, "buyer_protection_fee": 1.99,
                           "is_free": False, "installments": ["installments3x", "installments4x"]}
    assert parsers._euros(44990) == 449.9 and parsers._euros(None) is None and parsers._euros("x") is None


def test_dates_are_paris_time_turned_into_utc():
    ad = parsers.parse_search(load("search_iphone_15.json"), 1, 5)["ads"][0]
    # raw: first_publication_date "2026-11-08 11:50:37", index_date "2026-11-19 13:53:38" (Paris, UTC+1 in November)
    assert ad["published_at"] == "2026-11-08T10:50:37Z" and ad["updated_at"] == "2026-11-19T12:53:38Z"
    assert ad["expires_at"] is None


def test_ad_location_and_seller():
    ad = parsers.parse_search(load("search_iphone_15.json"), 1, 5)["ads"][0]
    assert ad["location"] == {
        "label": "Mulhouse 68100", "address": None, "city": "Mulhouse", "zipcode": "68100", "district": None,
        "department": {"id": "68", "name": "Haut-Rhin"}, "region": {"id": "1", "name": "Alsace"}, "country": "FR",
        "latitude": 47.7517, "longitude": 7.34367, "precision": "city", "is_area": True}
    seller = ad["seller"]
    assert seller["id"] == "5e3d331b-29ab-45e3-a36b-a83be13d5b05" and seller["type"] == "private"
    assert seller["link"] == "https://www.leboncoin.fr/profile/5e3d331b-29ab-45e3-a36b-a83be13d5b05/offers"
    assert seller["account_id"] == "77042114" and seller["siren"] is None and seller["store"] is None
    assert ad["images"]["count"] == 2 and len(ad["images"]["links"]) == 2
    assert ad["images"]["links"][0].endswith("?rule=ad-large") and ad["images"]["thumbnail"].endswith("?rule=ad-thumb")


def test_fields_read_out_of_the_attributes():
    # the site keeps the seller's picture and rating, the old price and all of shipping in `attributes`
    ads = {ad["id"]: ad for ad in parsers.parse_ads(load("ads_by_id.json"))}
    first, second = ads[3285245707], ads[3277956465]
    assert first["seller"]["picture"].endswith("?rule=pp-small")
    assert first["shipping"] == {
        "is_shippable": True, "methods": ["mondial_relay", "shop2shop", "colissimo", "face_to_face"],
        "fees": first["shipping"]["fees"], "parcel_weight_grams": 486, "parcel_size": "M", "ships_from_country": "FR"}
    assert first["shipping"]["fees"][0] == {"method": "mondial_relay", "amount": 2.49, "currency": "EUR"}
    assert first["price"]["installments"] == ["installments3x", "installments4x"] and first["price"]["previous_amount"] is None
    assert second["price"]["previous_amount"] == 380            # raw attribute old_price "380"
    wanted = parsers.parse_search(load("search_demand.json"), 1, 5)["ads"]
    # raw: rating_score 0.68 of 1, rating_count 5
    assert (wanted[0]["seller"]["rating"], wanted[0]["seller"]["reviews_count"]) == (3.4, 5)
    cars = parsers.parse_search(load("search_cars_filters.json"), 1, 2)["ads"]
    assert cars[0]["seller"]["store"] == {
        "id": 93849, "name": "SPOTICAR STELLANTIS & YOU VENISSIEUX ETATS-UNIS",
        "link": "https://www.leboncoin.fr/boutique/93849", "logo": cars[0]["seller"]["store"]["logo"]}
    assert cars[0]["seller"]["store"]["logo"].startswith("https://img.leboncoin.fr/")
    assert cars[0]["seller_reference"] == "749628" and cars[0]["shipping"]["is_shippable"] is None
    assert parsers.parse_ad({"list_id": 1, "attributes": [{"key": "donation", "value": "1"}]})["price"]["is_free"] is True


def test_attributes_keep_token_and_label_and_leave_out_what_has_its_own_field():
    ad = parsers.parse_search(load("search_iphone_15.json"), 1, 5)["ads"][0]
    assert attribute(ad, "condition") == {"key": "condition", "name": "État", "value": "tresbonetat", "label": "Très bon état"}
    keys = {a["key"] for a in ad["attributes"]}
    assert not keys & {"profile_picture_url", "rating_score", "shipping_type", "purchase_cta_visible", "is_bundleable"}


def test_car_ad_of_a_pro():
    found = parsers.parse_search(load("search_cars_filters.json"), 1, 2)
    assert found["pagination"] == {"page": 1, "items_per_page": 2, "total_pages": 345, "total_count": 689}
    assert (found["private_count"], found["pro_count"]) == (0, 689)
    car = found["ads"][0]
    assert car["title"] == "Peugeot 208 PureTech 75 S&S BVM5 Like" and car["price"]["amount"] == 9989
    assert car["seller"]["type"] == "pro" and car["seller"]["siren"] == "302475041"
    assert car["seller"]["activity_sector_id"] == 1 and car["seller"]["is_solicitation_refused"] is True
    assert car["seller"]["name"] == "SPOTICAR STELLANTIS & YOU VENISIEUX SALENGRO"
    assert attribute(car, "mileage") == {"key": "mileage", "name": "Kilométrage", "value": "54573", "label": "54573 km"}
    assert attribute(car, "fuel")["value"] == "1" and attribute(car, "fuel")["label"] == "Essence"
    # a multi-value attribute: tokens joined, labels as the site prints them
    specs = attribute(car, "vehicle_interior_specs")
    assert specs["value"].startswith("automatic_headlights, bluetooth") and "Climatisation" in specs["label"]
    assert car["highlights"] == ["Crit'Air 1", "Régulateur de vitesse", "Bluetooth"]
    assert car["promotion"]["is_boosted"] is True and car["is_urgent"] is False


def test_a_day_first_date_in_an_attribute_comes_out_iso():
    assert parsers._attribute({"key": "available_date", "value": "24/08/2026", "value_label": "24/08/2026"}) == {
        "key": "available_date", "name": None, "value": "2026-08-24", "label": "2026-08-24"}
    # a month and year is not a date, and a number with slashes is left alone
    assert parsers._attribute({"key": "issuance_date", "value": "07/2022", "value_label": "07/2022"})["value"] == "07/2022"
    assert parsers._iso_if_date("99/99/2026") == "99/99/2026" and parsers._iso_if_date(None) is None


def test_promoted_strip_is_kept_apart_and_never_repeats_the_page():
    found = parsers.parse_search(load("search_cars_filters.json"), 1, 2)
    page_ids = [ad["id"] for ad in found["ads"]]
    assert page_ids == [3297271486, 3287063034]
    assert [ad["id"] for ad in found["promoted_ads"]] == [3265465796, 3313036076, 3251618753]


def test_rental_ad():
    found = parsers.parse_search(load("search_rentals_lyon.json"), 1, 3)
    flat = found["ads"][0]
    assert flat["id"] == 3313358387 and flat["price"]["amount"] == 895
    assert flat["highlights"] == ["RDC", "Terrasse", "Parking / Garage", "Cave", "2 chambres"]
    assert attribute(flat, "square") == {"key": "square", "name": "Surface habitable", "value": "52", "label": "52 m²"}
    assert attribute(flat, "energy_rate")["label"] == "B"
    assert flat["seller"]["rates_link"].endswith("289044.pdf")
    assert "pro_rates_link" not in {a["key"] for a in flat["attributes"]}
    plans = [len(ad["images"]["floor_plan_links"]) for ad in found["ads"] + found["promoted_ads"]]
    assert sum(plans) == 2


def test_wanted_ads_have_no_price():
    ads = parsers.parse_search(load("search_demand.json"), 1, 5)["ads"]
    assert {ad["ad_type"] for ad in ads} == {"demand"}
    assert all(ad["price"]["amount"] is None and ad["price"]["currency"] is None for ad in ads)
    assert ads[0]["expires_at"] == "2027-01-19T12:02:10Z"
    no_empty_strings(ads)


def test_search_with_no_result():
    found = parsers.parse_search(load("search_no_result.json"), 1, 35)
    assert found["ads"] == [] and found["private_count"] is None
    assert found["pagination"] == {"page": 1, "items_per_page": 35, "total_pages": 0, "total_count": 0}


def test_page_past_the_end_is_an_empty_page():
    found = parsers.parse_search(load("search_past_end.json"), 101, 35)
    assert found["ads"] == []
    assert found["pagination"] == {"page": 101, "items_per_page": 35, "total_pages": None, "total_count": None,
                                   "has_next": False}


def test_ads_by_id_come_in_the_order_asked_and_name_the_missing():
    batch = parsers.parse_bulk(load("ads_by_id.json"), ["3277956465", "9999999999", "3285245707"])
    assert [ad["id"] for ad in batch["ads"]] == [3277956465, 3285245707]
    assert batch["not_found"] == [9999999999]
    assert parsers.parse_bulk(load("ads_by_id_not_found.json"), ["9999999999"]) == {"ads": [], "not_found": [9999999999]}


def test_similar_ads():
    ads = parsers.parse_ads(load("similar_ads.json"))
    assert [ad["id"] for ad in ads] == [3275961095, 2919267395, 3200767616]
    assert all(ad["link"].startswith("https://www.leboncoin.fr/ad/") for ad in ads)


def test_ad_parser_takes_a_bare_record():
    ad = parsers.parse_ad({"list_id": 5})
    assert ad["id"] == 5 and ad["title"] is None and ad["price"]["amount"] is None and ad["attributes"] == []
    assert ad["images"] == {"count": 0, "thumbnail": None, "links": [], "floor_plan_links": []}
    assert parsers.parse_ad(None) is None and parsers.parse_ads({}) == [] and parsers.parse_ads(None) == []


# ---- sellers -------------------------------------------------------------------------

def test_private_seller_with_reviews():
    seller = parsers.parse_seller(load("seller_private_rated.json"))
    assert seller["id"] == "148417de-bb7d-4cd2-87c9-7dfb5ccff35e" and seller["name"] == "Mathéo"
    assert seller["type"] == "private" and seller["location"] == "Ardèche" and seller["registered_date"] == "2019-07-12"
    # raw: overall_score 0.98 of 1 -> the 4.9 of 5 the site shows
    assert seller["rating"] == 4.9 and seller["reviews_count"] == 48
    assert {"name": "communication", "rating": 4.85} in seller["rating_categories"]
    assert seller["badges"] == ["recommended_seller", "responsiveness2", "verified_phone_number"]
    assert seller["is_phone_verified"] is True
    assert seller["reply"] == {"rate_percent": 86, "time_minutes": 360, "rate_text": "Répond à 86 % des messages",
                               "time_text": "Répond en moyenne en 6 heures"}
    assert seller["presence"]["status"] == "offline" and seller["presence"]["last_active_at"] == "2026-11-20T11:45:39Z"
    assert seller["website"] is None and seller["company"] is None and seller["store"] is None
    assert seller["followers_count"] is None
    assert list(seller)[:7] == ["id", "name", "link", "type", "description", "location", "website"]
    no_empty_strings(seller)


def test_private_seller_without_reviews():
    seller = parsers.parse_seller(load("seller_private_plain.json"))
    assert seller["rating"] is None and seller["reviews_count"] == 0 and seller["rating_categories"] == []
    assert seller["location"] is None and seller["description"] is None


def test_pro_seller_with_company_and_store():
    seller = parsers.parse_seller(load("seller_pro.json"), company=load("seller_pro_company.json"),
                                  store=load("store_338302.json"), followers=load("followers.json"))
    assert seller["type"] == "pro" and seller["name"] == "SIMSIZE" and seller["followers_count"] == 57
    assert seller["website"] == "http://simsize.fr/"
    assert seller["company"] == {"name": "SIMSIZE", "siren": "791208762", "siret": "79120876200017",
                                 "activity_sector": "job", "activity_sector_id": 8, "category_id": "71",
                                 "address": "40 rue d'alsace lorraine", "zipcode": "31000", "city": "Toulouse",
                                 "is_dsa_self_certified": False}
    store = seller["store"]
    assert store["id"] == 338302 and store["name"] == "SIMSIZE MOBILE"
    assert store["link"] == "https://www.leboncoin.fr/boutique/338302" and store["website"] == "http://simsize.fr/"
    assert store["owner_id"] == "031c778f-f4bd-4969-98a8-179c1f4efd2f" and store["active_since"] == "2017-03-14"
    assert store["opening_hours"] == "Horaire d'ouverture :\ndu lundi au samedi 10H-12H30 13h30-19h"
    assert store["address"]["street"] == "40 RUE D ALSACE LORRAINE" and store["address"]["zipcode"] == "31000"
    assert store["address"]["department"] == {"id": "31", "name": "Haute-Garonne"}
    assert (store["address"]["latitude"], store["address"]["longitude"]) == (43.60595, 1.44586)
    assert store["has_phone"] is True and store["has_contact_form"] is True
    assert store["team"] == [{"name": "Laura", "position": "responsable de magasin", "picture": None}]
    assert store["services"] == ["Aménagement des horaires"]
    assert store["promotion"]["title"] == "Promo Iphone 11 noel" and store["external_rating"] is None
    no_empty_strings(seller)


def test_agency_store():
    store = parsers.parse_store(load("store_agency.json"))
    assert store["name"] == "MY CASA IMMOBILIER" and store["website"] == "http://www.mycasa-immobilier.com"
    assert store["sold_properties_count"] == 17 and len(store["team"]) >= 5
    assert store["team"][0]["name"] == "Enzo MOLINA" and store["team"][0]["picture"].startswith("https://img.leboncoin.fr/")
    assert store["activity_zone"]["city"] == "Lyon" and store["activity_zone"]["radius_km"] == 20
    assert "Estimation de prix" in store["services"]


def test_store_with_a_google_maps_rating():
    rating = parsers.parse_store(load("store_rated.json"))["external_rating"]
    assert (rating["source"], rating["rating"], rating["reviews_count"]) == ("Google Maps", 4.8, 348)
    assert rating["link"].startswith("https://maps.google.com/") and rating["retrieved_at"] == "2026-11-17T23:20:32Z"
    assert len(rating["reviews"]) == 5 and rating["reviews"][0]["date"] == "2026-11-07T09:01:38Z"


@pytest.mark.parametrize("value, expected", [
    ("http://simsize.fr/", "http://simsize.fr/"),
    ("www.example.fr", "http://www.example.fr"),
    ("https://www.leboncoin.fr/boutique/1", None),
    ("pas de site", None), ("", None), (None, None),
])
def test_store_website(value, expected):
    assert parsers._website(value) == expected


def test_store_and_company_of_a_private_seller_are_none():
    assert parsers.parse_store(None) is None and parsers.parse_store({}) is None
    assert parsers.parse_company(None) is None and parsers.parse_company({}) is None


# ---- reviews -------------------------------------------------------------------------

def test_reviews_page():
    parsed = parsers.parse_reviews(load("reviews_page_1.json"), 1, 5)
    assert parsed["pagination"] == {"page": 1, "items_per_page": 5, "total_count": 48, "total_pages": 10}
    summary = parsed["summary"]
    assert (summary["rating"], summary["reviews_count"], summary["written_reviews_count"]) == (4.9, 48, 15)
    assert (summary["as_seller_count"], summary["as_buyer_count"]) == (34, 14)
    assert (summary["member_reviews_count"], summary["automatic_reviews_count"]) == (31, 17)
    first, second = parsed["reviews"][:2]
    assert first["id"] == 269802274 and first["rating"] == 4.0 and first["date"] == "2026-11-08T14:46:06Z"
    assert first["text"] == "Transaction ok , tous c'est bien passé" and first["is_automatic"] is False
    assert first["reviewer"]["id"] == "381b362b-2374-45c0-a43b-8b6cda921bd4" and first["reviewer"]["rating"] == 4.95
    assert first["item"]["title"] == "Circuit train sncf bois"
    # the site's own automatic review: no id, and its author is not a member with a profile
    assert second["is_automatic"] is True and second["id"] is None and second["reviewer"]["link"] is None
    no_empty_strings(parsed)


def test_reviews_past_the_end_and_unknown_user():
    past = parsers.parse_reviews(load("reviews_past_end.json"), 50, 5)
    assert past["reviews"] == [] and past["pagination"]["total_count"] == 48 and past["pagination"]["total_pages"] == 10
    none = parsers.parse_reviews(None, 1, 20)
    assert none["reviews"] == [] and none["summary"]["reviews_count"] == 0 and none["summary"]["rating"] is None
    assert none["pagination"] == {"page": 1, "items_per_page": 20, "total_count": 0, "total_pages": 0}


# ---- suggestions and locations ---------------------------------------------------------

def test_suggestions(reference):
    rows = parsers.parse_suggestions(load("suggestions_iphone.json"), reference["by_id"])
    assert rows[0] == {"text": "iphone 15", "category": {"id": "17", "name": "Téléphones & Objets connectés",
                                                         "slug": "telephones_objets_connectes"}}
    assert {"text": "iphone 15", "category": None} in rows        # cat_id -1: every category
    assert parsers.parse_suggestions({}) == [] and parsers.parse_suggestions(None) == []


def test_locations_carry_the_value_a_search_takes():
    rows = parsers.parse_locations(load("locations_lyon.json"))
    assert rows[0]["value"] == "Lyon__45.76248594304118_4.82856614424162_8479" and rows[0]["type"] == "city"
    assert rows[1] == {"value": "Lyon_69003__45.75898_4.86114_3774", "type": "city", "label": "Lyon (69003)",
                       "city": "Lyon", "zipcode": "69003", "place": None, "department_id": "69", "region_id": "22",
                       "country": None, "latitude": 45.75898, "longitude": 4.86114, "default_radius_meters": 3774}
    values = [row["value"] for row in parsers.parse_locations(load("locations_rhone.json"))]
    assert values[:5] == ["d_69", "dn_69", "p_Vallée du Rhône__44.426422119140625_4.886382102966309_5000", "r_22", "rn_22"]
    assert parsers.parse_locations([]) == [] and parsers.parse_locations(None) == []


def test_a_location_value_reads_back_into_the_site_object():
    from leboncoin import refs
    for raw in load("locations_lyon.json") + load("locations_rhone.json"):
        again = refs.resolve_location(refs.location_token(raw))[0]
        assert again["locationType"] == raw["locationType"]
        for key in ("department_id", "region_id", "zipcode"):
            if raw["locationType"] != "city" or key == "zipcode":
                assert again.get(key) == raw.get(key) or key not in again
        if "area" in raw:
            assert (again["area"]["lat"], again["area"]["lng"]) == (raw["area"]["lat"], raw["area"]["lng"])


# ---- reference data ------------------------------------------------------------------

def test_categories(reference):
    assert len(reference["categories"]) == 14 and len(reference["by_id"]) == 114
    cars = reference["by_id"]["2"]
    assert cars["name"] == "Voitures" and cars["slug"] == "voitures" and cars["parent_id"] == "1"
    assert cars["link"] == "https://www.leboncoin.fr/c/voitures" and cars["same_as"] is None
    assert {t["type"] for t in cars["ad_types"]} == {"offer", "demand"}
    assert reference["by_slug"]["voitures"] == "2" and reference["by_slug"]["véhicules"] == "1"
    # a slug is its own category's, whatever group carries the same name ("Animaux": the group 75, the category 28)
    assert reference["by_slug"]["animaux"] == "28" and reference["by_slug"]["_animaux_"] == "75"
    # a "mirror" category is another category with a filter
    assert reference["by_id"]["2001"]["same_as"] == {"category_id": "9", "filters": [{"key": "immo_sell_type", "value": "new"}]}
    # one the site only links out to
    assert reference["by_id"]["300"]["external_link"].startswith("https://www.truckscorner.fr/") and reference["by_id"]["300"]["link"] is None
    vehicles = next(c for c in reference["categories"] if c["id"] == "1")
    assert "2" in [s["id"] for s in vehicles["subcategories"]]


def test_filters_of_a_category(reference):
    rows = parsers.parse_category_filters(reference, "2")
    keys = [row["key"] for row in rows]
    assert keys[:5] == ["price", "monthly_payment_price", "u_car_brand", "u_car_model", "u_car_finition"]
    by_key = {row["key"]: row for row in rows}
    assert by_key["fuel"]["type"] == "choice" and by_key["fuel"]["is_multiple"] is True
    assert {"value": "1", "label": "Essence", "group": None} in by_key["fuel"]["values"]
    assert by_key["mileage"]["type"] == "range" and by_key["mileage"]["unit"] == "km" and by_key["mileage"]["values"] is None
    assert len(by_key["u_car_brand"]["values"]) == 164 and by_key["u_car_brand"]["values"][0]["group"] == "Marques Courantes"
    # a model list depends on the brand: named, with no values, until the brand is chosen
    assert by_key["u_car_model"]["depends_on"] == "u_car_brand" and by_key["u_car_model"]["values"] is None


def test_dependent_filter_opens_with_its_parent(reference):
    rows = parsers.parse_category_filters(reference, "2", {"u_car_brand": ["PEUGEOT"]})
    models = next(row for row in rows if row["key"] == "u_car_model")
    assert models["depends_on"] == "u_car_brand" and len(models["values"]) == 55
    assert {"value": "PEUGEOT_208", "label": "208", "group": None} in models["values"]


def test_filters_of_rentals_and_of_an_unknown_category(reference):
    rows = parsers.parse_category_filters(reference, "10")
    assert [row["key"] for row in rows][:5] == ["real_estate_type", "price", "rooms", "bedrooms", "square"]
    assert parsers.parse_category_filters(reference, "99999") == []


# ---- queries: the search body ----------------------------------------------------------

def test_search_body_like_the_sites_own():
    body = queries.search_body(text="velo", title_only=True, category_id="55", include_delivery=True,
                               locations=[{"locationType": "region", "region_id": "12"}], sort="price_asc")
    assert body == {"filters": {"enums": {"ad_type": ["offer"]}, "category": {"id": "55"},
                                "keywords": {"text": "velo", "type": "subject"},
                                "location": {"shippable": True, "locations": [{"locationType": "region", "region_id": "12"}]}},
                    "sort_by": "price", "limit": 35, "sort_order": "asc"}
    assert "inject_alu" not in body


def test_search_body_paging_radius_and_owner():
    city = {"locationType": "city", "area": {"lat": 1.0, "lng": 2.0, "default_radius": 5000}}
    body = queries.search_body(text="velo", locations=[city, {"locationType": "department", "department_id": "69"}],
                               radius_km=30, page=3, limit=50, seller_type="pro")
    assert body["offset"] == 100 and body["limit"] == 50 and body["owner_type"] == "pro" and "sort_order" not in body
    assert body["filters"]["location"]["locations"][0]["area"] == {"lat": 1.0, "lng": 2.0, "default_radius": 5000, "radius": 30000}
    assert body["filters"]["location"]["locations"][1] == {"locationType": "department", "department_id": "69"}
    assert city["area"] == {"lat": 1.0, "lng": 2.0, "default_radius": 5000}      # the caller's object is left alone
    point = {"locationType": "city", "area": {"lat": 1.0, "lng": 2.0, "radius": 10000}}
    assert queries.search_body(locations=[point], radius_km=50)["filters"]["location"]["locations"][0]["area"]["radius"] == 50000
    assert queries.search_body(limit=500)["limit"] == 100
    seller = queries.search_body(owner_user_id="u-1", sort="newest")
    assert seller["filters"]["owner"] == {"user_id": "u-1"} and (seller["sort_by"], seller["sort_order"]) == ("time", "desc")


def test_ads_body():
    assert queries.ads_body(["1", "2"]) == {"filters": {}, "limit": 2, "pivot": '{"ids_to_display":["1","2"]}'}
    assert queries.ads_body([str(n) for n in range(150)])["limit"] == 100


@pytest.mark.parametrize("text, expected", [
    ("500-1500", {"min": 500, "max": 1500}), ("min-100000", {"max": 100000}), ("2018-max", {"min": 2018}),
    ("-900", {"max": 900}), ("3", {"min": 3, "max": 3}),
])
def test_range(text, expected):
    assert queries.parse_range("x", text) == expected


@pytest.mark.parametrize("text", ["abc", "min-max", "9-3", "1.5-2"])
def test_range_rejects(text):
    with pytest.raises(ValueError):
        queries.parse_range("mileage", text)


def test_filters_are_checked_against_the_sites_list(reference):
    pairs = [["fuel", "1|Diesel"], ["mileage", "min-100000"], ["regdate", "2018-max"], ["u_car_model", "peugeot_208"],
             ["urgent", "1"], ["u_car_finition", "PEUGEOT_208_Like"], ["shippable", "true"]]
    enums, ranges = queries.check_filters(pairs, reference["params"])
    # a label is turned into its token, a token is matched whatever its case, an open list passes as written
    assert enums == {"fuel": ["1", "2"], "u_car_model": ["PEUGEOT_208"], "urgent": ["1"],
                     "u_car_finition": ["PEUGEOT_208_Like"], "shippable": ["true"]}
    assert ranges == {"mileage": {"max": 100000}, "regdate": {"min": 2018}}


@pytest.mark.parametrize("pairs, fragment", [
    ([["nope", "1"]], "no filter named 'nope'"),
    ([["fuel", "99"]], "'fuel' has no value '99'"),
    ([["mileage", "abc"]], "is a range"),
    ([["urgent", "maybe"]], "is a switch"),
    ([["date", "2026-12-01-2026-12-08"]], "date range"),
])
def test_filters_reject(reference, pairs, fragment):
    with pytest.raises(ValueError) as error:
        queries.check_filters(pairs, reference["params"])
    assert fragment in str(error.value)
