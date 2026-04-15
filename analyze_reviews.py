"""
RevBusters – LLM Review Analysis Engine
Uses Claude Haiku to classify reviews as fake/genuine/uncertain
and estimate the true rating.
"""

import json
import re
import os
import anthropic
from dotenv import load_dotenv

load_dotenv()

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

PROMPT = """You are an expert at detecting fake Google reviews for ANY local business — restaurants, salons, spas, dentists, clinics, service shops, hotels, retail stores, etc.
I will give you a JSON array of reviews scraped from Google Maps.
TASK
Analyze all reviews and classify each as:

* "fake" → high confidence manipulation or coordinated behavior
* "genuine" → clearly authentic human experience
* "uncertain" → insufficient evidence either way (DEFAULT for low-signal reviews)
IMPORTANT PRINCIPLE
Do NOT classify a review as "fake" based on low effort alone. Short, generic, or vague reviews are NOT fake by default — they are uncertain unless there is evidence of coordination or manipulation.
FAKE signals
Classify as fake if there is clear evidence of manipulation, such as:
1. Coordinated / templated patterns (REQUIRED for most fake calls)

* 5 reviews sharing near-identical sentence structure
* Repeated phrasing patterns with only minor word swaps
* Same unusual spelling/error repeated across multiple accounts
2. Promotional or scripted intent

* Business name unnaturally inserted ("Best [business name] in Gurgaon")
* Overly promotional tone that feels like marketing copy
* Repeated "must visit", "best in city", "10/10 highly recommended" across many reviews
3. Reviewer credibility red flags (ONLY when combined with patterns)

* Many reviewers with 1 total review, AND similar wording
* Bulk reviews posted in tight time clusters with similar structure
4. Implausible or mismatched content

* Services described don't match the business
* Reviewer persona mismatch (e.g., irrelevant business account, impossible experience)
A single signal is NOT enough — look for patterns across multiple reviews
GENUINE signals

* Mentions specific service + outcome
* Names staff naturally (without formal titles like Mr./Sir)
* Includes personal context (first visit, pain relief, etc.)
* Uses natural or imperfect language (Hinglish, casual tone)
* Mixed sentiment (minor complaints + positives)
* Negative reviews from experienced reviewers (very high credibility)
UNCERTAIN signals (DEFAULT BUCKET)
Classify as uncertain if the review can't be classified as genuine or fake.
CROSS-REVIEW ANALYSIS (VERY IMPORTANT)
Before labeling anything as fake, check:

* Are there 3+ reviews with the same structure?
* Are the same phrases repeated unnaturally?
* Is there a clear pattern, or just coincidence?
If NO strong pattern → classify as uncertain, not fake
After classifying, estimate the TRUE RATING (1.0–5.0, one decimal) this business deserves based ONLY on what genuine customers actually experienced — ignoring all fake reviews entirely. Weight by specificity, tone, and sentiment of genuine reviews. Give extra weight to negative reviews from high-credibility accounts.

Return ONLY a JSON object in exactly this format (no markdown, no explanation):
{
  "fake": <count>,
  "genuine": <count>,
  "uncertain": <count>,
  "true_rating": <float>
}"""

# Trust level thresholds based on fake %
FAKE_THRESHOLD       = 35   # fake_pct >= 35 → "fake"
SUSPICIOUS_THRESHOLD = 15   # fake_pct >= 15 → "suspicious"


def analyze(reviews_data: dict) -> dict:
    meta = reviews_data["meta"]
    raw  = reviews_data["reviews"]

    if not raw:
        raise ValueError("No reviews to analyse.")

    # Compact reviews — only fields the LLM needs
    compact = []
    for r in raw:
        compact.append({
            "stars":                   r.get("stars"),
            "text":                    r.get("text"),
            "reviewerNumberOfReviews": r.get("reviewerNumberOfReviews"),
            "isLocalGuide":            r.get("isLocalGuide"),
            "categoryName":            r.get("categoryName"),
            "publishAt":               r.get("publishAt"),
        })

    user_msg = (
        f"Business: {meta['business_name']}\n"
        f"Category: {meta.get('category', 'Unknown')}\n"
        f"Google Rating: {meta['total_google_rating']} ({meta['total_google_reviews']} total reviews)\n"
        f"Reviews analyzed: {len(compact)}\n\n"
        f"REVIEWS JSON:\n{json.dumps(compact, ensure_ascii=False)}"
    )

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=500,
        messages=[{"role": "user", "content": PROMPT + "\n\n" + user_msg}],
    )

    raw_text = response.content[0].text.strip()
    clean    = re.sub(r'^```json\s*|\s*```$', '', raw_text, flags=re.MULTILINE).strip()
    llm      = json.loads(clean)

    total        = llm["fake"] + llm["genuine"] + llm["uncertain"]
    fake_pct     = round(llm["fake"]      / total * 100) if total > 0 else 0
    genuine_pct  = round(llm["genuine"]   / total * 100) if total > 0 else 0
    uncertain_pct= round(llm["uncertain"] / total * 100) if total > 0 else 0
    ai_rating    = round(float(llm["true_rating"]), 1)
    google_rating= meta.get("total_google_rating") or 5.0

    # Trust level
    if fake_pct >= FAKE_THRESHOLD:
        trust_level = "fake"
        trust_label = "Likely Fake Reviews"
    elif fake_pct >= SUSPICIOUS_THRESHOLD:
        trust_level = "suspicious"
        trust_label = "Suspicious Activity"
    else:
        trust_level = "genuine"
        trust_label = "Likely Genuine"

    # Build narrative signals
    signals = []
    if fake_pct >= 30:
        signals.append({
            "icon":   "🤖",
            "title":  f"{fake_pct}% reviews appear fake",
            "detail": "AI detected coordinated patterns — templated text, scripted promotions, or suspicious reviewer profiles repeating across multiple reviews.",
        })
    if genuine_pct <= 20 and fake_pct >= 20:
        signals.append({
            "icon":   "👥",
            "title":  f"Only {genuine_pct}% reviews appear genuine",
            "detail": "Very few reviews show authentic personal experience, specific details, or natural language that indicates a real customer.",
        })
    if uncertain_pct >= 40:
        signals.append({
            "icon":   "❓",
            "title":  f"{uncertain_pct}% reviews are low-signal",
            "detail": "A large share of reviews are too short or vague to verify — typical when fake campaigns dilute review quality.",
        })

    return {
        "meta":          meta,
        "trust_level":   trust_level,
        "trust_label":   trust_label,
        "google_rating": google_rating,
        "ai_rating":     ai_rating,
        "total_google":  meta.get("total_google_reviews") or len(raw),
        "fake_pct":      fake_pct,
        "genuine_pct":   genuine_pct,
        "uncertain_pct": uncertain_pct,
        "signals":       signals,
    }


if __name__ == "__main__":
    import sys
    path = sys.argv[1] if len(sys.argv) > 1 else "reviews_output.json"
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    result = analyze(data)
    print(json.dumps(result, indent=2))
