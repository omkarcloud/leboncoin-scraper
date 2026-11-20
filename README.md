# 🚀 Leboncoin Scraper

Leboncoin Scraper is a **free and open-source** scraper that gets you **unlimited** detailed Leboncoin data for free.

## ✨ What Can I Get?

- 🏷️ **Full details of 95M+ ads** — price, description, every attribute, all photos, GPS location, seller & shipping fees
- 🔍 **Search all of France in 114 categories** — keywords, place & radius, price, private or pro, sort & each category's own filters
- 🏪 **Sellers behind 4.5M+ pro ads** — company SIREN & SIRET, store page, website, opening hours, followers, rating & every review
- 🚗 **815K+ cars & 1.2M+ property ads** — make, model, year, mileage, fuel, rooms, living area & energy rating as plain filters

## 💍 Example: A Full Leboncoin Ad

```json
{
  "id": 2300724612,
  "title": "Bracelet Pandora",
  "link": "https://www.leboncoin.fr/ad/montres_bijoux/2300724612",
  "status": "active",
  "description": "Bracelet Pandora jonc ouvert\nTaille 2 soit 17,5cm\nTrès bon état\nGravure S925 ALE\nFourni avec boîte",
  "category": { "id": "42", "name": "Montres & Bijoux", "slug": "montres_bijoux" },
  "price": { "amount": 44, "currency": "EUR", "buyer_protection_fee": 2.9, "is_free": false },
  "has_phone": true,
  "stock_quantity": 1,
  "images": { "count": 5, "links": ["https://img.leboncoin.fr/api/v1/lbcpb1/images/c6/c9/8d/c6c98de97a58bb80ff26d3ca95d5c6dd861941fe.jpg?rule=ad-large"] },
  "attributes": [
    { "key": "condition", "name": "État", "value": "etatneuf", "label": "État neuf" },
    { "key": "accessories_univers", "name": "Univers", "value": "femme", "label": "Femme" },
    { "key": "watches_jewels_brand", "name": "Marque", "value": "pandora", "label": "Pandora" },
    { "key": "watches_jewels_material", "name": "Matière", "value": "argent", "label": "Argent" }
  ],
  "location": { "label": "Montauban 82000", "city": "Montauban", "zipcode": "82000", "department": { "id": "82", "name": "Tarn-et-Garonne" }, "region": { "id": "16", "name": "Midi-Pyrénées" }, "latitude": 44.01824, "longitude": 1.35958 },
  "seller": { "id": "08d6871a-789b-48ff-af30-15dfaeadf3af", "name": "Les trésors de Caro", "type": "pro", "siren": "909430290" },
  "shipping": { "is_shippable": true, "methods": ["mondial_relay", "colissimo", "click_and_collect"], "fees": [{ "method": "mondial_relay", "amount": 0.99, "currency": "EUR" }, { "method": "colissimo", "amount": 7.59, "currency": "EUR" }] },
  "published_at": "2023-02-14T11:26:37Z"
}
```

*Trimmed for readability.*

## 🚀 Unlimited Free Leboncoin Data — Get It in 60 Seconds

1️⃣ Clone and install:
```bash
git clone https://github.com/omkarcloud/leboncoin-scraper
cd leboncoin-scraper
python -m pip install -r requirements.txt
```

2️⃣ Start the API:
```bash
python run.py
```

Leboncoin works from your own connection, no proxy needed. If Leboncoin starts refusing you at volume, set `LEBONCOIN_PROXY=http://user:pass@host:port` to a French residential proxy and keep going.

3️⃣ Get your first data:
```bash
curl "http://localhost:8000/ads/details?ad=2300724612"
```

```json
{
  "id": 2300724612,
  "title": "Bracelet Pandora",
  "link": "https://www.leboncoin.fr/ad/montres_bijoux/2300724612",
  "status": "active",
  "category": { "id": "42", "name": "Montres & Bijoux", "slug": "montres_bijoux" },
  "price": { "amount": 44, "currency": "EUR", "buyer_protection_fee": 2.9 },
  "images": { "count": 5, "thumbnail": "https://img.leboncoin.fr/api/v1/lbcpb1/images/c6/c9/8d/c6c98de97a58bb80ff26d3ca95d5c6dd861941fe.jpg?rule=ad-thumb" },
  "attributes": [
    { "key": "watches_jewels_type", "name": "Type", "value": "bracelet", "label": "Bracelet" },
    { "key": "watches_jewels_brand", "name": "Marque", "value": "pandora", "label": "Pandora" }
  ],
  "location": { "city": "Montauban", "zipcode": "82000", "latitude": 44.01824, "longitude": 1.35958 },
  "seller": { "id": "08d6871a-789b-48ff-af30-15dfaeadf3af", "name": "Les trésors de Caro", "type": "pro" },
  "shipping": { "is_shippable": true, "methods": ["mondial_relay", "colissimo", "click_and_collect"] },
  "published_at": "2023-02-14T11:26:37Z"
}
```

All 11 endpoints are now live at `http://localhost:8000`.

## 📚 Endpoints

11 endpoints cover everything you need.

| Endpoint | Path | Returns |
|---|---|---|
| Ad Details / Bulk | `/ads/details`, `/ads/bulk` | The whole ad in one call, or up to 100 at once |
| Search Suggestions | `/search/suggestions` | Leboncoin's own search suggestions as you type |
| Search Ads | `/ads/search` | 95M+ ads with keyword, place, price and category filters |
| Similar Ads | `/ads/similar` | Ads that look like this one, matched by photo |
| Seller Details | `/sellers/details` | Company, store, website, rating and followers (website contacts: hosted API only) |
| Seller Ads / Reviews | `/sellers/ads`, `/sellers/reviews` | Every ad a seller has online and every review they got |
| Search Locations | `/locations/search` | Cities, postcodes and departments with coordinates |
| Categories / Filters | `/categories/list`, `/categories/filters` | All 114 categories and each one's own search filters |

## 🔍 Exploring Parameters

The same API is published on RapidAPI, and its playground is the easiest place to try parameters and see raw responses. Once a request looks right, run it locally for **unlimited free** data.

1. [Subscribe to the free plan](https://rapidapi.com/OmkarCloud/api/best-leboncoin-scraper-free-1000-calls/pricing) — 1,000 calls/month, no credit card.
2. [Try the endpoints in the playground](https://rapidapi.com/OmkarCloud/api/best-leboncoin-scraper-free-1000-calls/playground) — every param is pre-filled, so you see real data in one click.
3. Copy the generated code and replace `https://best-leboncoin-scraper-free-1000-calls.p.rapidapi.com` with `http://localhost:8000`. It will now run against your local API.

```python
import requests

# generated by the playground, host swapped for the local API
response = requests.get(
    "http://localhost:8000/ads/details",
    params={"ad": "2300724612"},
)
print(response.json())
```

## 💬 Have Questions? We Have Answers.

You're a developer — we know how hard completing a project can be. So we offer full support: just message us and we'll reply ✅ with a solution within 1 working day.

[![Message Us on WhatsApp about Leboncoin Scraper](https://raw.githubusercontent.com/omkarcloud/assets/master/images/whatsapp-us.png)](https://www.omkar.cloud/l/leboncoin-scraper-github-whatsapp)

[![Ask Us by Email about Leboncoin Scraper](https://raw.githubusercontent.com/omkarcloud/assets/master/images/ask-on-email.png)](mailto:happy.to.help@omkar.cloud?subject=Help%20with%20Leboncoin%20Scraper%20API&body=I%20need%20help%20using%20the%20Leboncoin%20Scraper%20API.)

## ⚡ Popular Scrapers by Omkar Cloud

- [**Google Maps Scraper (3,100+ GitHub Stars)**](https://github.com/omkarcloud/google-maps-scraper) — type "dentists in New York", get every business as a ready-to-call lead list: phones, emails, websites & reviews. Up to 100K free leads/month.
- [**G2 Scraper**](https://www.omkar.cloud/tools/g2-scraper) — G2 product details, ratings & AI-found contacts
- [**Website Email Contact Scraper**](https://www.omkar.cloud/tools/website-email-contact-scraper) — emails, phones & socials from any website
- [**AliExpress Scraper**](https://www.omkar.cloud/tools/aliexpress-scraper-api) — live product details, SKU variants, stock & shipping
- [**Booking Scraper**](https://www.omkar.cloud/tools/booking-scraper) — Booking.com hotels: prices, ratings, rooms & amenities
- [**Etsy Scraper**](https://www.omkar.cloud/tools/etsy-scraper) — Etsy products: prices, discounts, shops & variations

## ⭐ Love It? [Star It ⭐!](https://github.com/omkarcloud/leboncoin-scraper)

Star the repo ⭐ and become my star hero!

It's just 1 click, but it means the world to me.

[![Star us on GitHub](https://raw.githubusercontent.com/omkarcloud/google-maps-scraper/master/screenshots/star-us.png)](https://github.com/omkarcloud/leboncoin-scraper)
