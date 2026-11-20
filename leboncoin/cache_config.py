"""Cache TTL per /leboncoin/* surface (cache.py, keyed on the validated
params). Leboncoin is a live classifieds board: the newest ads of a busy
search are seconds old, and an ad can be sold or withdrawn at any moment.
"""
from datetime import timedelta

# ads/search and sellers/ads: new ads land every second; a page of results
# older than a few minutes misses them (and "newest" is the sort buyers use)
SEARCH_CACHE = timedelta(minutes=10)
# ads/details and ads/bulk: an ad's price and status (sold, expired) change
# without notice
AD_CACHE = timedelta(minutes=30)
# ads/similar: the site's visual match over the live board
SIMILAR_CACHE = timedelta(hours=1)
# sellers/details: the card's "last seen" and reply rate move through the
# day; the company record and the store page barely move
SELLER_CACHE = timedelta(hours=6)
# a store page asked by its own id (to find its owner): changes when the
# pro edits it
STORE_CACHE = timedelta(hours=24)
# sellers/reviews: a seller gains a review after a sale, a few a week at most
REVIEWS_CACHE = timedelta(hours=6)
# search/suggestions: the suggestion model follows what people type, slowly
SUGGESTIONS_CACHE = timedelta(hours=24)
# locations/search and a place name resolved for a search: France's cities
# and postcodes do not move
LOCATIONS_CACHE = timedelta(days=30)
# categories/list and categories/filters, answered from the reference data
CATEGORIES_CACHE = timedelta(hours=24)

# The reference data itself (categories, regions, every filter: 0.7 MB) is
# kept parsed in the process for this long, one fetch per process.
REFERENCE_SECONDS = 24 * 3600
