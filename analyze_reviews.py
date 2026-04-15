"""
RevBusters – LLM Review Analysis Engine
Uses Claude Sonnet for holistic fake review detection.
No pre-computed stats — Sonnet performs all pattern identification itself.
"""

import json
import re
import os
import anthropic
from dotenv import load_dotenv

load_dotenv()

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

PROMPT = """You are an expert at detecting fake Google reviews for ANY local business — restaurants, salons, spas, dentists, clinics, diagnostic labs, service shops, hotels, online delivery/gifting services, retail stores, etc.

Read ALL the reviews below as a complete dataset, not one by one. Your job is to identify coordinated manipulation patterns that only become visible when you look across many reviews together.

━━━ STEP 1: CROSS-REVIEW PATTERN SCAN (do this first) ━━━
Before classifying anything, scan the full set and note:
1. Star distribution — what % are 5-star? A real business almost always has some 1–3 star reviews. 100% five-star across 50+ reviews is a very strong fake signal, especially for service businesses like labs, clinics, or delivery services.
2. Templated batches — look for groups of reviews that share the same sentence structure with minor word swaps (e.g. "Best X in town — affordable, quick, and reliable!", "Highly impressed with X and affordable rates!", "Convenient X, perfect for people with busy schedules."). 3+ reviews with near-identical phrasing = scripted campaign.
3. Near-duplicate phrasing across different accounts — word-for-word matches with minor punctuation differences signal a shared script.
4. SEO keyword/location stuffing — reviews that insert neighbourhood names, pin codes, or road names ("Excellent service sec 49 Gurgaon sohna road") with no personal experience. Real customers don't write like that.
5. Full multi-word business name insertion — real customers say "they", "this place", "the lab", not the full registered brand name mid-sentence. Ghost accounts with 0–1 reviews inserting the full name = SEO farming.
6. Bulk no-text ghost ratings — large numbers of 5-star ratings with zero review text from accounts with 0–2 total reviews ever. For service businesses where customers would normally comment on experience, this is a bulk rating campaign.
7. Voice uniformity — do all reviews sound like they were written by the same person or follow the same promotional arc?

━━━ CALIBRATION BY BUSINESS TYPE ━━━
Different business types have different baseline review behaviour — apply these before flagging:

ONLINE DELIVERY / GIFTING / E-COMMERCE:
• Short, generic positive reviews ARE normal — customers order, receive, leave 5 stars with minimal text.
• Email-style writing ("I placed an order and paid Rs. X, received on time") can be genuine — remote customers write differently than walk-in customers.
• Phrases like "Must try it", "highly recommend", "best service" are very common in this category — do NOT flag these alone as fake.
• Flag only when: ghost account (0–1 reviews) + full brand name inserted + zero personal detail, ALL together.

IN-PERSON SERVICES (clinics, labs, salons, workshops, restaurants):
• Customers almost always mention something specific — the procedure, the staff member, the wait time, the environment.
• Generic promotional reviews with no personal detail ("Best diagnostic center in town — affordable, quick, and reliable!") are suspicious here.
• 100% five-star with no complaints across 50+ reviews is a very strong fake signal for this category.
• Bulk no-text ghost ratings are especially suspicious for in-person services.

PREMIUM / HOTEL SPA / HIGH-END:
• "Highly recommend", "exceptional experience", "must visit" are common from genuine guests — do not flag these alone.
• Look for corroborating signals (voice uniformity, templated batches) before calling suspicious.

━━━ STEP 2: CLASSIFY EACH REVIEW ━━━
• "fake"     → clear evidence of coordination or scripted behaviour
• "genuine"  → clearly authentic human experience
• "uncertain"→ not enough signal either way

FAKE signals:
• Templated batch: 3+ reviews with near-identical structure and word swaps (strongest signal)
• Near-duplicate phrasing across different accounts
• SEO location/keyword stuffing in review text
• Ghost account (0–1 reviews ever) + full multi-word brand name inserted + no personal detail
• Bulk no-text 5-star ratings from ghost accounts (for in-person service businesses)
• 100% five-star across 50+ reviews for in-person service businesses

GENUINE signals (these strongly override fake suspicion):
• Specific procedure, product, or personal outcome ("PRP treatment, painless", "ordered Rakhi to Taran Taran")
• Staff members named — especially DIFFERENT staff names across reviews (fake campaigns cannot coordinate this)
• Mixed sentiment or small complaints ("waiting time was long", "could improve packaging")
• Negative or mixed reviews from experienced reviewers (high review count, Local Guide) — highest credibility signal
• International customers with specific travel/location context
• Natural imperfect language — Hinglish, typos, casual shorthand
• Specific comparisons to competitors or alternatives ("even FnP wasn't delivering there")

UNCERTAIN — use when genuinely ambiguous:
Short or vague reviews with no fake AND no genuine signals. No-text ratings from accounts with 3+ reviews can be uncertain rather than fake. If Step 1 found strong cross-review patterns, apply them even to short reviews that fit the mould.

━━━ STEP 3: TRUE RATING ━━━
Estimate the TRUE RATING (1.0–5.0, one decimal) the business deserves based ONLY on genuine reviews. Weight by specificity, sentiment, and credibility. Negative reviews from experienced reviewers count heavily.

Return ONLY a JSON object — no markdown, no explanation:
{
  "fake": <count>,
  "genuine": <count>,
  "uncertain": <count>,
  "true_rating": <float>
}"""

HIGHLY_SUSPICIOUS_THRESHOLD = 35
SUSPICIOUS_THRESHOLD        = 15


def analyze(reviews_data: dict) -> dict:
    meta = reviews_data["meta"]
    raw  = reviews_data["reviews"]

    if not raw:
        raise ValueError("No reviews to analyse.")

    # Compact reviews for LLM
    compact = [
        {
            "stars":                   r.get("stars"),
            "text":                    r.get("text"),
            "reviewerNumberOfReviews": r.get("reviewerNumberOfReviews"),
            "isLocalGuide":            r.get("isLocalGuide"),
            "categoryName":            r.get("categoryName"),
            "publishAt":               r.get("publishAt"),
        }
        for r in raw
    ]

    user_msg = (
        f"Business: {meta['business_name']}\n"
        f"Category: {meta.get('category', 'Unknown')}\n"
        f"Google Rating: {meta['total_google_rating']} ({meta['total_google_reviews']} total reviews)\n"
        f"Reviews analysed: {len(compact)}\n\n"
        f"REVIEWS JSON:\n{json.dumps(compact, ensure_ascii=False)}"
    )

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2000,
        messages=[{"role": "user", "content": PROMPT + "\n\n" + user_msg}],
    )

    raw_text = response.content[0].text.strip()
    # Strip markdown code fences if present
    clean = re.sub(r'```(?:json)?\s*', '', raw_text).strip()
    # Extract first JSON object found in the response
    match = re.search(r'\{[\s\S]*\}', clean)
    if not match:
        raise ValueError(f"LLM returned no JSON. Raw response: {raw_text[:300]}")
    llm = json.loads(match.group())

    total         = llm["fake"] + llm["genuine"] + llm["uncertain"]
    fake_pct      = round(llm["fake"]      / total * 100) if total > 0 else 0
    genuine_pct   = round(llm["genuine"]   / total * 100) if total > 0 else 0
    uncertain_pct = round(llm["uncertain"] / total * 100) if total > 0 else 0
    ai_rating     = round(float(llm["true_rating"]), 1)
    google_rating = meta.get("total_google_rating") or 5.0

    # Trust level
    if fake_pct >= HIGHLY_SUSPICIOUS_THRESHOLD:
        trust_level = "highly-suspicious"
        trust_label = "Highly Suspicious"
    elif fake_pct >= SUSPICIOUS_THRESHOLD:
        trust_level = "suspicious"
        trust_label = "Suspicious"
    else:
        trust_level = "genuine"
        trust_label = "Genuine"

    suspicious_pct = fake_pct   # rename for user-facing output

    # Build signals
    signals = []
    if suspicious_pct >= 30:
        signals.append({
            "icon":   "🤖",
            "title":  f"{suspicious_pct}% reviews are suspicious",
            "detail": "AI detected coordinated patterns — templated text, scripted promotions, or suspicious reviewer profiles repeating across multiple reviews.",
        })
    if genuine_pct <= 20 and suspicious_pct >= 20:
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
        "meta":           meta,
        "trust_level":    trust_level,
        "trust_label":    trust_label,
        "google_rating":  google_rating,
        "ai_rating":      ai_rating,
        "total_google":   meta.get("total_google_reviews") or len(raw),
        "suspicious_pct": suspicious_pct,
        "genuine_pct":    genuine_pct,
        "uncertain_pct":  uncertain_pct,
        "signals":        signals,
    }


if __name__ == "__main__":
    import sys
    path = sys.argv[1] if len(sys.argv) > 1 else "reviews_output.json"
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    result = analyze(data)
    print(json.dumps(result, indent=2))
