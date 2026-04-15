"""
RevBusters – Offline Review Analysis Engine
Signals: TF-IDF duplicates, ghost accounts, velocity spikes, empty reviews
No LLM tokens consumed.
"""

import json
import numpy as np
from datetime import datetime
from collections import defaultdict
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity


# ── Thresholds ──────────────────────────────────────────────────────────────
TFIDF_DUP_THRESHOLD    = 0.70   # cosine sim above this → duplicate
SPIKE_MULTIPLIER       = 3.0    # week count > 3× avg → spike
SPIKE_MIN_REVIEWS      = 5      # spike week must have at least this many
GHOST_MAX_REVIEWS      = 1      # reviewer with ≤ this many total reviews is ghost
MIN_SIGNALS_FOR_FAKE   = 2      # review needs ≥ 2 signals to be labelled fake

TRUST_GENUINE_DELTA    = 0.2    # google - ai ≤ 0.2 → Likely Genuine
TRUST_SUSPICIOUS_DELTA = 0.6    # ≤ 0.6 → Suspicious


def _parse_reviews(raw: list) -> list:
    parsed = []
    for r in raw:
        text = (r.get("text") or "").strip()
        stars = r.get("stars") or 5
        total_rev = r.get("reviewerNumberOfReviews") or 0
        is_lg = bool(r.get("isLocalGuide", False))

        date_str = r.get("publishedAtDate", "") or ""
        try:
            pub_date = datetime.fromisoformat(date_str[:10]) if date_str else None
        except ValueError:
            pub_date = None

        parsed.append({
            "id":              r.get("reviewId", ""),
            "name":            r.get("name", ""),
            "stars":           stars,
            "text":            text,
            "reviewer_reviews": total_rev,
            "is_local_guide":  is_lg,
            "date":            pub_date,
            "is_empty":        len(text) < 5,
            "is_ghost":        total_rev <= GHOST_MAX_REVIEWS and not is_lg,
        })
    return parsed


def _velocity_signals(parsed: list):
    """Return (spike_week_set, weekly_avg, weekly_counts_dict)."""
    weekly_counts = defaultdict(int)
    for r in parsed:
        if r["date"]:
            yw = r["date"].isocalendar()[:2]   # (year, week_number)
            weekly_counts[yw] += 1

    if not weekly_counts:
        return set(), 0.0, {}

    counts = list(weekly_counts.values())
    weekly_avg = sum(counts) / len(counts)
    spike_weeks = {
        wk for wk, cnt in weekly_counts.items()
        if cnt >= SPIKE_MIN_REVIEWS and cnt > SPIKE_MULTIPLIER * weekly_avg
    }
    return spike_weeks, weekly_avg, weekly_counts


def _tfidf_signals(parsed: list):
    """Return (flagged_indices_set, avg_max_sim, example_pairs)."""
    texts = [r["text"] for r in parsed]
    non_empty_idx = [i for i, t in enumerate(texts) if len(t) >= 5]

    if len(non_empty_idx) < 2:
        return set(), 0.0, []

    ne_texts = [texts[i] for i in non_empty_idx]
    try:
        vec = TfidfVectorizer(ngram_range=(1, 2), min_df=1)
        mat = vec.fit_transform(ne_texts)
        sim = cosine_similarity(mat)
        np.fill_diagonal(sim, 0)
    except Exception:
        return set(), 0.0, []

    max_sims = sim.max(axis=1)
    avg_max_sim = float(np.mean(max_sims))

    flagged = set()
    example_pairs = []
    seen = set()
    for local_i, s in enumerate(max_sims):
        if s >= TFIDF_DUP_THRESHOLD:
            global_i = non_empty_idx[local_i]
            flagged.add(global_i)
            # collect one example pair
            local_j = int(np.argmax(sim[local_i]))
            global_j = non_empty_idx[local_j]
            pair = tuple(sorted([global_i, global_j]))
            if pair not in seen:
                seen.add(pair)
                preview = texts[global_i][:60].strip()
                example_pairs.append(preview)

    return flagged, avg_max_sim, example_pairs[:3]


def _score_reviews(parsed, spike_weeks, tfidf_flagged):
    """Attach fake_signals, is_fake, is_suspicious to each review."""
    for i, r in enumerate(parsed):
        if r["date"]:
            r["in_spike_week"] = r["date"].isocalendar()[:2] in spike_weeks
        else:
            r["in_spike_week"] = False

        r["is_tfidf_duplicate"] = i in tfidf_flagged

        sigs = sum([
            r["is_ghost"],
            r["is_empty"],
            r["in_spike_week"],
            r["is_tfidf_duplicate"],
        ])
        r["fake_signals"] = sigs
        r["is_fake"]       = sigs >= MIN_SIGNALS_FOR_FAKE
        r["is_suspicious"] = sigs == 1


def _trust_level(delta: float, ghost_pct: float, spike_count: int, duplicate_pct: float):
    """
    Combined suspicion score — rating delta alone is not enough
    because fake reviews on 5-star businesses don't shift the average.
    """
    score = 0.0

    # Rating delta (inflated rating signal)
    score += delta * 2.0

    # Ghost account concentration
    if ghost_pct >= 0.40:
        score += 1.5
    elif ghost_pct >= 0.25:
        score += 0.75

    # Velocity spikes
    if spike_count >= 3:
        score += 1.0
    elif spike_count >= 2:
        score += 0.5

    # Duplicate / copy-paste reviews
    if duplicate_pct >= 0.30:
        score += 1.0
    elif duplicate_pct >= 0.15:
        score += 0.5

    if score < 1.0:
        return "genuine", "Likely Genuine"
    elif score < 2.5:
        return "suspicious", "Suspicious Activity"
    else:
        return "fake", "Likely Fake Reviews"


def _build_signals(parsed, ghost_pct, spike_count, weekly_avg,
                   weekly_counts, duplicate_count, example_pairs):
    signals = []

    n = len(parsed)

    if duplicate_count >= 3:
        dup_pct = round(duplicate_count / n * 100)
        signals.append({
            "icon": "📋",
            "title": "Copy-paste reviews",
            "detail": (
                f"Identical or near-identical text found across ~{dup_pct}% of reviews."
            )
        })

    if spike_count >= 2:
        max_wk = max(weekly_counts.values()) if weekly_counts else 0
        signals.append({
            "icon": "📈",
            "title": "Review farming detected",
            "detail": (
                f"Usually receives ~{weekly_avg:.0f} reviews/week, but had "
                f"{spike_count} week{'s' if spike_count > 1 else ''} with "
                f"{max_wk}+ reviews each — consistent with bulk-purchased campaigns."
            )
        })

    if ghost_pct >= 0.15:
        signals.append({
            "icon": "👻",
            "title": f"{round(ghost_pct * 100)}% ghost reviewers",
            "detail": (
                "Reviewers who have only given a single 5-star rating to this place "
                "in their entire Google history."
            )
        })

    return signals


def analyze(reviews_data: dict) -> dict:
    meta    = reviews_data["meta"]
    raw     = reviews_data["reviews"]
    parsed  = _parse_reviews(raw)
    n       = len(parsed)

    if n == 0:
        raise ValueError("No reviews to analyse.")

    # --- signals ---
    spike_weeks, weekly_avg, weekly_counts = _velocity_signals(parsed)
    tfidf_flagged, avg_max_sim, example_pairs = _tfidf_signals(parsed)
    _score_reviews(parsed, spike_weeks, tfidf_flagged)

    # --- aggregates ---
    ghost_n    = sum(1 for r in parsed if r["is_ghost"])
    empty_n    = sum(1 for r in parsed if r["is_empty"])
    fake_n     = sum(1 for r in parsed if r["is_fake"])
    susp_n     = sum(1 for r in parsed if r["is_suspicious"])
    genuine_n  = n - fake_n

    ghost_pct  = ghost_n / n
    empty_pct  = empty_n / n

    # --- AI predicted rating ---
    # Use actual sample star distribution (more precise than Google's rounded display).
    # Remove estimated fake 5★ reviews from both numerator and denominator.
    #   sample_avg   = actual average from scraped reviews
    #   fake_stars   = 5 × estimated_fake_count  (fake reviews are almost always 5★)
    #   ai_rating    = (sample_avg × total - fake_stars) / (total - fake_count)
    total_google      = meta.get("total_google_reviews") or n
    google_rating_raw = meta.get("total_google_rating") or 5.0
    fake_rate         = fake_n / n if n > 0 else 0
    est_fake_total    = fake_rate * total_google
    est_genuine_total = max(1, total_google - est_fake_total)

    # Use sample average as base (captures actual 1★/4★ reviews, not just rounded display)
    sample_avg = sum(r["stars"] for r in parsed) / n if n > 0 else google_rating_raw
    total_stars_est = sample_avg * total_google
    fake_stars      = 5.0 * est_fake_total
    ai_rating       = (total_stars_est - fake_stars) / est_genuine_total
    ai_rating       = max(1.0, min(round(ai_rating, 1), google_rating_raw))

    estimated_genuine = max(1, round(est_genuine_total))

    # --- trust level ---
    google_rating = meta.get("total_google_rating") or 5.0
    delta         = google_rating - ai_rating
    duplicate_pct = len(tfidf_flagged) / n if n > 0 else 0
    trust_level, trust_label = _trust_level(delta, ghost_pct, len(spike_weeks), duplicate_pct)

    # --- narrative signals ---
    signals = _build_signals(
        parsed, ghost_pct, len(spike_weeks), weekly_avg,
        weekly_counts, len(tfidf_flagged), example_pairs
    )

    return {
        "meta":              meta,
        "trust_level":       trust_level,
        "trust_label":       trust_label,
        "google_rating":     google_rating,
        "ai_rating":         ai_rating,
        "total_google":      total_google,
        "estimated_genuine": estimated_genuine,
        "scraped":           n,
        "fake_n":            fake_n,
        "suspicious_n":      susp_n,
        "genuine_n":         genuine_n,
        "ghost_pct":         ghost_pct,
        "empty_pct":         empty_pct,
        "avg_max_sim":       avg_max_sim,
        "spike_count":       len(spike_weeks),
        "weekly_avg":        weekly_avg,
        "duplicate_count":   len(tfidf_flagged),
        "signals":           signals,
    }


if __name__ == "__main__":
    import sys
    path = sys.argv[1] if len(sys.argv) > 1 else "reviews_output.json"
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    result = analyze(data)
    print(json.dumps(result, indent=2, default=str))
