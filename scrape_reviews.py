import os
import json
import sys
import re
import requests
from urllib.parse import urlparse, parse_qs
from apify_client import ApifyClient
from dotenv import load_dotenv

load_dotenv()

API_TOKEN = os.getenv("APIFY_API_TOKEN")


def resolve_url(url: str) -> dict:
    """
    Resolves any Google Maps URL format to place name + kgmid.
    Supports:
    - share.google/...
    - maps.app.goo.gl/...
    - google.com/maps/place/...
    - google.com/maps?cid=...
    """
    headers = {"User-Agent": "Mozilla/5.0"}

    # Follow redirects to get final URL
    r = requests.get(url, headers=headers, allow_redirects=True, timeout=10)
    final_url = r.url

    # Extract kgmid from search redirect (share.google resolves to this)
    kgmid_match = re.search(r'kgmid=(/g/[a-zA-Z0-9_]+)', final_url)
    kgmid = kgmid_match.group(1) if kgmid_match else None

    # Extract place name from query param
    name_match = re.search(r'[?&]q=([^&]+)', final_url)
    place_name = name_match.group(1).replace('+', ' ') if name_match else None

    # Handle standard /maps/place/NAME/ URLs
    if not place_name and '/maps/place/' in final_url:
        place_match = re.search(r'/maps/place/([^/@]+)', final_url)
        place_name = place_match.group(1).replace('+', ' ') if place_match else None

    return {
        "place_name": place_name,
        "kgmid": kgmid,
        "resolved_url": final_url
    }


def _calculate_scrape_limit(total_reviews) -> int:
    """
    Scrape limit formula:
    - If 50% of total > 200  → scrape 200
    - If 50% of total < 100  → scrape min(total, 100)
    - Otherwise              → scrape 50% of total
    """
    try:
        x = int(total_reviews)
    except (TypeError, ValueError):
        return 200
    if x <= 0:
        return 200
    half = x * 0.5
    if half > 200:
        return 200
    elif half < 100:
        return min(x, 100)
    else:
        return int(half)


def _run_apify(client, search_url: str, max_reviews: int) -> list:
    run_input = {
        "startUrls": [{"url": search_url}],
        "maxReviews": max_reviews,
        "reviewsSort": "newest",
    }
    run = client.actor("compass/google-maps-reviews-scraper").call(run_input=run_input)
    return list(client.dataset(run["defaultDatasetId"]).iterate_items())


def scrape_reviews(google_maps_url: str, max_reviews: int = None) -> dict:
    """
    Takes any Google Maps URL and returns reviews for the specific place.
    If max_reviews is None, dynamically calculates limit based on total review count.
    """
    client = ApifyClient(API_TOKEN)

    # Resolve URL to get place name and kgmid
    print(f"Resolving URL: {google_maps_url}")
    resolved = resolve_url(google_maps_url)
    place_name = resolved["place_name"]
    kgmid = resolved["kgmid"]

    print(f"Place: {place_name} | kgmid: {kgmid}")

    # Build search URL for Apify
    search_url = f"https://www.google.com/maps/search/{place_name}" if place_name else google_maps_url

    # Step 1: if no limit given, fetch 3 reviews to get total count, then calculate limit
    if max_reviews is None:
        print("Fetching metadata to calculate scrape limit...")
        sample = _run_apify(client, search_url, max_reviews=3)
        if kgmid:
            sample = [r for r in sample if r.get("kgmid") == kgmid] or sample
        total = sample[0].get("reviewsCount", 0) if sample else 0
        max_reviews = _calculate_scrape_limit(total)
        print(f"Total reviews on Google: {total} → scraping {max_reviews}")

    print(f"Scraping {max_reviews} reviews... (this takes ~30-60 seconds)")
    run = client.actor("compass/google-maps-reviews-scraper").call(run_input={
        "startUrls": [{"url": search_url}],
        "maxReviews": max_reviews,
        "reviewsSort": "newest",
    })

    all_reviews = list(client.dataset(run["defaultDatasetId"]).iterate_items())


    # Filter to the specific place using kgmid if available
    if kgmid:
        filtered = [r for r in all_reviews if r.get("kgmid") == kgmid]
        print(f"Filtered {len(all_reviews)} → {len(filtered)} reviews for kgmid {kgmid}")
        reviews = filtered if filtered else all_reviews
    else:
        reviews = all_reviews

    # Extract business metadata from first review
    meta = {}
    if reviews:
        first = reviews[0]
        meta = {
            "business_name": first.get("title"),
            "address": first.get("address"),
            "category": first.get("categoryName"),
            "total_google_rating": first.get("totalScore"),
            "total_google_reviews": first.get("reviewsCount"),
            "kgmid": first.get("kgmid"),
            "cid": first.get("cid"),
        }

    return {"meta": meta, "reviews": reviews}


def save_results(data: dict, output_file: str = "reviews_output.json"):
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"Saved to {output_file}")


if __name__ == "__main__":
    url = sys.argv[1] if len(sys.argv) > 1 else "https://share.google/uRQhOj2OGHgqK7RuW"

    data = scrape_reviews(url)

    meta = data["meta"]
    reviews = data["reviews"]

    print(f"\n=== {meta.get('business_name', 'Unknown')} ===")
    print(f"Address  : {meta.get('address')}")
    print(f"Category : {meta.get('category')}")
    print(f"Rating   : {meta.get('total_google_rating')} ({meta.get('total_google_reviews')} reviews)")
    print(f"Reviews fetched: {len(reviews)}")

    if reviews:
        print("\n--- Sample Review ---")
        r = reviews[0]
        print(f"Reviewer : {r.get('name')} ({r.get('reviewerNumberOfReviews')} total reviews)")
        print(f"Rating   : {r.get('stars')}")
        print(f"Text     : {r.get('text', '')[:200]}")
        print(f"Date     : {r.get('publishedAtDate')}")

    save_results(data)
