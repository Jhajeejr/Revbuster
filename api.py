"""
RevBusters – Flask API
Endpoints:
  GET  /ping     → warmup / health check
  POST /analyze  → { "url": "..." } → analysis JSON (cache-first)
  GET  /history  → last 50 analyses
"""

import os
import re
import json
import traceback
import requests
from flask import Flask, request, jsonify
from flask_cors import CORS
from dotenv import load_dotenv

from scrape_reviews import scrape_reviews
from analyze_reviews import analyze

load_dotenv()

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})

SUPABASE_URL      = os.environ.get("SUPABASE_URL")
SUPABASE_ANON_KEY = os.environ.get("SUPABASE_ANON_KEY")


def _sb_headers(prefer_minimal=False):
    h = {
        "apikey":        SUPABASE_ANON_KEY,
        "Authorization": f"Bearer {SUPABASE_ANON_KEY}",
        "Content-Type":  "application/json",
    }
    if prefer_minimal:
        h["Prefer"] = "return=minimal"
    return h


# ── URL normalisation helpers ────────────────────────────────────────────────

def expand_url(url):
    """Follow redirects for shortened Google Maps URLs (goo.gl / maps.app.goo.gl)."""
    if "goo.gl" in url:
        try:
            r = requests.head(url, allow_redirects=True, timeout=8)
            return r.url
        except Exception:
            pass
    return url


def extract_place_id(url):
    """Pull the stable Google Place ID out of a Maps URL data parameter."""
    # ChIJ… format (most common)
    m = re.search(r'!1s(ChIJ[^!&?]+)', url)
    if m:
        return m.group(1)
    # 0x… hex format
    m = re.search(r'!1s(0x[0-9a-fA-F]+:[^!&?]+)', url)
    if m:
        return m.group(1)
    return None


def normalize_url(url):
    """Strip coordinates and data noise for consistent URL matching."""
    url = re.sub(r'/@[^/]+', '', url)      # remove /@lat,lng,zoom
    url = re.sub(r'/data=.*$', '', url)    # remove /data=...
    url = re.sub(r'\?.*$', '', url)        # remove query string
    return url.rstrip('/')


# ── Cache helpers ────────────────────────────────────────────────────────────

def lookup_cache(place_id, norm_url):
    """Return the first matching Supabase row, or None."""
    if not SUPABASE_URL or not SUPABASE_ANON_KEY:
        return None
    try:
        base = f"{SUPABASE_URL}/rest/v1/analyses"
        h    = _sb_headers()

        if place_id:
            r = requests.get(
                f"{base}?place_id=eq.{requests.utils.quote(place_id, safe='')}&limit=1",
                headers=h, timeout=8
            )
            if r.status_code == 200:
                rows = r.json()
                if rows:
                    return rows[0]

        if norm_url:
            r = requests.get(
                f"{base}?place_url=eq.{requests.utils.quote(norm_url, safe='')}&limit=1",
                headers=h, timeout=8
            )
            if r.status_code == 200:
                rows = r.json()
                if rows:
                    return rows[0]
    except Exception as e:
        print(f"[cache] lookup error: {e}")
    return None


def row_to_result(row):
    """Convert a Supabase analyses row into the result dict the frontend expects."""
    return {
        "meta": {
            "business_name": row.get("business_name"),
            "address":       row.get("address"),
            "category":      row.get("category"),
        },
        "trust_level":    row.get("trust_level"),
        "trust_label":    row.get("trust_label"),
        "google_rating":  row.get("google_rating"),
        "ai_rating":      row.get("ai_rating"),
        "total_google":   row.get("total_google"),
        "suspicious_pct": row.get("suspicious_pct"),
        "genuine_pct":    row.get("genuine_pct"),
        "uncertain_pct":  row.get("uncertain_pct"),
        "signals":        row.get("signals") or [],
        "cached":         True,
    }


# ── Flask routes ─────────────────────────────────────────────────────────────

@app.after_request
def add_cors_headers(response):
    response.headers["Access-Control-Allow-Origin"]  = "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    return response

@app.route("/analyze",  methods=["OPTIONS"])
def analyze_preflight():  return "", 204

@app.route("/history",  methods=["OPTIONS"])
def history_preflight():  return "", 204

@app.route("/ping", methods=["GET"])
def ping():
    return jsonify({"status": "ok"})


@app.route("/analyze", methods=["POST"])
def analyze_url():
    body = request.get_json(silent=True) or {}
    url  = (body.get("url") or "").strip()

    if not url:
        return jsonify({"error": "url is required"}), 400

    if "google" not in url and "goo.gl" not in url:
        return jsonify({"error": "Please paste a Google Maps URL"}), 400

    try:
        # ── Normalise URL & extract stable Place ID ──────────────────────
        expanded  = expand_url(url)
        place_id  = extract_place_id(expanded)
        norm_url  = normalize_url(expanded)
        print(f"[analyze] place_id={place_id}  norm_url={norm_url}")

        # ── Cache check (always use cache) ───────────────────────────────
        cached = lookup_cache(place_id, norm_url)
        if cached:
            print(f"[analyze] Cache hit → {cached.get('business_name')}")
            return jsonify(row_to_result(cached))

        # ── Full scrape + LLM analysis ───────────────────────────────────
        print(f"[analyze] Cache miss — scraping: {url}")
        reviews_data = scrape_reviews(url)

        if not reviews_data.get("reviews"):
            return jsonify({"error": "No reviews found for this place"}), 404

        print("[analyze] Running LLM analysis…")
        result = analyze(reviews_data)

        save_to_supabase(result, place_id=place_id, place_url=norm_url)

        return jsonify(_sanitize(result))

    except Exception as e:
        traceback.print_exc()
        import sys
        print(f"[ERROR] {type(e).__name__}: {e}", file=sys.stderr)
        return jsonify({"error": f"{type(e).__name__}: {str(e)}"}), 500


@app.route("/history", methods=["GET"])
def get_history():
    """Return last 50 analyses from Supabase."""
    if not SUPABASE_URL or not SUPABASE_ANON_KEY:
        return jsonify([])
    try:
        url      = f"{SUPABASE_URL}/rest/v1/analyses?select=*&order=created_at.desc&limit=200"
        response = requests.get(url, headers=_sb_headers(), timeout=8)
        if response.status_code == 200:
            return jsonify(response.json())
        print(f"[history] Supabase error: {response.status_code} {response.text}")
        return jsonify([])
    except Exception as e:
        print(f"[history] Error: {e}")
        return jsonify([])


def save_to_supabase(result, place_id=None, place_url=None):
    """Persist an analysis result to Supabase."""
    if not SUPABASE_URL or not SUPABASE_ANON_KEY:
        return
    try:
        meta = result.get("meta", {})
        payload = {
            "business_name": meta.get("business_name"),
            "address":       meta.get("address"),
            "category":      meta.get("category"),
            "google_rating": result.get("google_rating"),
            "ai_rating":     result.get("ai_rating"),
            "trust_level":   result.get("trust_level"),
            "trust_label":   result.get("trust_label"),
            "suspicious_pct":result.get("suspicious_pct"),
            "genuine_pct":   result.get("genuine_pct"),
            "uncertain_pct": result.get("uncertain_pct"),
            "total_google":  result.get("total_google"),
            "signals":       result.get("signals", []),
            "place_id":      place_id,
            "place_url":     place_url,
        }
        url      = f"{SUPABASE_URL}/rest/v1/analyses"
        response = requests.post(url, json=payload, headers=_sb_headers(prefer_minimal=True), timeout=10)
        if response.status_code not in (200, 201):
            print(f"[save_to_supabase] Error: {response.status_code} {response.text}")
    except Exception as e:
        print(f"[save_to_supabase] Exception: {e}")


def _sanitize(obj):
    """Recursively make an object JSON-serialisable."""
    if isinstance(obj, dict):
        return {k: _sanitize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize(i) for i in obj]
    try:
        json.dumps(obj)
        return obj
    except (TypeError, ValueError):
        return str(obj)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
