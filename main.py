"""Use the scraper straight from Python, no server needed.

    python main.py

Each call validates its params with the same schema the API uses (so the
defaults apply) and returns the same JSON the API does, except that a list
keeps its `pagination` block instead of next / previous links. The results
are written to output/*.json.
"""
import json
import os

from leboncoin import api, schemas
from schema_fields import load_query

os.makedirs("output", exist_ok=True)


def run(schema_cls, impl, **params):
    data, error = load_query(schema_cls, {k: str(v) for k, v in params.items()})
    if error:
        raise ValueError(error)
    return impl(**data)


def save(name, data):
    path = os.path.join("output", name)
    with open(path, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"saved {path}")


if __name__ == "__main__":
    # A full ad: price, description, every attribute, all photos, GPS location, seller and shipping fees
    save("ads_details.json", run(schemas.AdsDetailsSchema, api.ads_details, ad='2300724612'))

    # Leboncoin's own search suggestions for what you type, each with its category
    save("search_suggestions.json", run(schemas.SearchSuggestionsSchema, api.search_suggestions, query='iphone 15'))

    # The first page of a search: 35 full ads, plus the total count and the private / pro split
    save("ads_search.json", run(schemas.AdsSearchSchema, api.ads_search, query='iphone 15'))
