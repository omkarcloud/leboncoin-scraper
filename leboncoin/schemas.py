"""Marshmallow request schemas for every /leboncoin/* route.

ONE param per input (never a sibling `url` / `id` pair):

    ad        an ad id (3091399005) OR a leboncoin.fr ad link
    ads       up to 100 of those, comma-separated
    seller    a user id (UUID), a profile link OR a pro store link
    query     keywords OR a whole leboncoin.fr search link, whose filters
              then apply (a param given next to it wins over the link's)
    category  a category id (2), its slug (voitures) OR a category link
    location  a place name or postcode, lat,lng, or a `value` of
              /leboncoin/locations/search; several separated by ';'
    filters   key:value pairs over the keys of /leboncoin/categories/filters

A search page holds 35 ads like the site's own, 100 at most; the site
serves a search 3,500 ads deep.
"""
from marshmallow import pre_load

from schema_fields import BaseSchema, ChoiceField, Flag, LimitField, PageField, PositiveInt, QueryField, RefField
from leboncoin import queries, refs

MAX_PAGE = 3500                 # limit=1 reaches the site's 3,500-ad depth on page 3500; past it a page is empty
MAX_REVIEWS_LIMIT = 300         # the review call's own default page; larger values were accepted, never needed
MAX_REVIEWS_PAGE = 10000
MAX_SIMILAR = 100               # what the site's own page asks for
MAX_PRICE = 100_000_000


class _Schema(BaseSchema):
    @pre_load
    def empty_is_absent(self, data, **kwargs):
        """An optional param sent empty (`category=`, `page=`: a form that
        sends every field) is the absent param; a required one sent empty
        is still refused."""
        required = {field.data_key or name for name, field in self.fields.items() if field.required}
        return {key: value for key, value in data.items()
                if key in required or not (isinstance(value, str) and not value.strip())}


class AdRefField(RefField):
    resolver = staticmethod(refs.resolve_ad)


class AdsRefField(RefField):
    """'3091399005, <link>' -> the ids, in order, repeats dropped."""
    resolver = staticmethod(refs.resolve_ads)


class SellerRefField(RefField):
    resolver = staticmethod(refs.resolve_seller)


class CategoryRefField(RefField):
    resolver = staticmethod(refs.resolve_category)


class LocationRefField(RefField):
    resolver = staticmethod(refs.resolve_location)


class FiltersRefField(RefField):
    resolver = staticmethod(refs.resolve_filters)


class SearchQueryField(RefField):
    """Keywords -> {"text": ...}; a leboncoin.fr search link -> {"link": {...}}."""
    resolver = staticmethod(refs.resolve_query)


def _page_field(max_page=MAX_PAGE):
    return PageField(max_page=max_page, metadata={"description": "page number, from 1"})


def _limit_field():
    return LimitField(default=queries.DEFAULT_LIMIT, max_size=queries.MAX_LIMIT,
                      metadata={"description": "ads per page: 35 like the site, up to 100"})


# ---- ads -----------------------------------------------------------------------------

class AdsSearchSchema(_Schema):
    query = SearchQueryField(required=False, load_default=None,
                             metadata={"description": "keywords (iphone 15), or a leboncoin.fr search link whose filters then apply"})
    category = CategoryRefField(required=False, load_default=None,
                                metadata={"description": "category id (2), slug (voitures) or link; /leboncoin/categories/list has them"})
    location = LocationRefField(required=False, load_default=None,
                                metadata={"description": "place name or postcode (Lyon, 33000, Bretagne), lat,lng, or a value "
                                                         "of /leboncoin/locations/search; several separated by ';'"})
    radius = PositiveInt(max_value=queries.MAX_RADIUS_KM,
                         metadata={"description": "km around a city or point, up to 200 (default: the city's own area)"})
    price_min = PositiveInt(max_value=MAX_PRICE, metadata={"description": "lowest price, euros"})
    price_max = PositiveInt(max_value=MAX_PRICE, metadata={"description": "highest price, euros"})
    seller_type = ChoiceField(dict(refs.SELLER_TYPES), metadata={"description": "private or pro (default: both)"})
    ad_type = ChoiceField(dict(refs.AD_TYPES), metadata={"description": "offer (default) or demand (wanted ads)"})
    sort = ChoiceField(list(refs.SORTS), metadata={"description": "relevance (default), newest, oldest, price_asc or price_desc"})
    title_only = Flag(metadata={"description": "true: match the keywords in the title only"})
    include_delivery = Flag(metadata={"description": "true, with a location: also ads from elsewhere that can be delivered"})
    urgent_only = Flag(metadata={"description": "true: only ads marked urgent"})
    free_only = Flag(metadata={"description": "true: only donations (free items)"})
    filters = FiltersRefField(required=False, load_default=None,
                              metadata={"description": "the category's own filters as key:value, comma-separated "
                                                       "(fuel:1|2,mileage:min-100000); /leboncoin/categories/filters lists them"})
    page = _page_field()
    limit = _limit_field()


class AdsDetailsSchema(_Schema):
    ad = AdRefField(metadata={"description": "ad id (3091399005) or a leboncoin.fr ad link"})


class AdsBulkSchema(_Schema):
    ads = AdsRefField(metadata={"description": "up to 100 ad ids or ad links, comma-separated"})


class AdsSimilarSchema(_Schema):
    ad = AdRefField(metadata={"description": "ad id (3091399005) or a leboncoin.fr ad link"})
    limit = LimitField(default=10, max_size=MAX_SIMILAR, metadata={"description": "ads to return, up to 100"})


# ---- sellers -------------------------------------------------------------------------

def _seller_field():
    return SellerRefField(metadata={"description": "seller's user id (the ad's seller.id), a profile link or a pro store "
                                                   "(boutique) link"})


class SellersDetailsSchema(_Schema):
    seller = _seller_field()


class SellersAdsSchema(_Schema):
    seller = _seller_field()
    page = _page_field()
    limit = _limit_field()


class SellersReviewsSchema(_Schema):
    seller = _seller_field()
    page = _page_field(MAX_REVIEWS_PAGE)
    limit = LimitField(default=20, max_size=MAX_REVIEWS_LIMIT, metadata={"description": "reviews per page, up to 300"})


# ---- suggestions, locations, categories ------------------------------------------------

class SearchSuggestionsSchema(_Schema):
    query = QueryField(max_length=100, metadata={"description": "the start of a search term"})


class LocationsSearchSchema(_Schema):
    query = QueryField(max_length=80, metadata={"description": "the start of a city, postcode, department or region name"})


class CategoriesListSchema(_Schema):
    pass


class CategoriesFiltersSchema(_Schema):
    category = CategoryRefField(metadata={"description": "category id (2), slug (voitures) or link"})
    filters = FiltersRefField(required=False, load_default=None,
                              metadata={"description": "filters already chosen, to open the ones that depend on them "
                                                       "(u_car_brand:PEUGEOT lists its models)"})

