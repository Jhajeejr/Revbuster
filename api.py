"""
RevBusters – Flask API
Endpoints:
  GET  /ping     → warmup / health check
  POST /analyze  → { "url": "..." } → analysis JSON
  GET  /history → last 50 analyses
"""

import os
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

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_ANON_KEY = os.environ.get("SUPABASE_ANON_KEY")

@app.after_request
def add_cors_headers(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    return response

@app.route("/analyze", methods=["OPTIONS"])
def analyze_preflight():
    return "", 204

@app.route("/history", methods=["OPTIONS"])
def history_preflight():
    return "", 204

@app.route("/ping", methods=["GET"])
def ping():
    return jsonify({"status": "ok"})


@app.route("/analyze", methods=["POST"])
def analyze_url():
    body = request.get_json(silent=True) or {}
    url = (body.get("url") or "").strip()

    if not url:
        return jsonify({"error": "url is required"}), 400

    if "google" not in url and "goo.gl" not in url:
        return jsonify({"error": "Please paste a Google Maps URL"}), 400

    try:
        print(f"[analyze] Scraping: {url}")
        reviews_data = scrape_reviews(url)

        if not reviews_data.get("reviews"):
            return jsonify({"error": "No reviews found for this place"}), 404

        print(f"[analyze] Running analysis...")
        result = analyze(reviews_data)

        # Save to Supabase
        save_to_supabase(result)

        # Make result JSON-safe (remove datetime objects etc.)
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
        headers = {
            "apikey": SUPABASE_ANON_KEY,
            "Authorization": f"Bearer {SUPABASE_ANON_KEY}",
            "Content-Type": "application/json",
        }
        url = f"{SUPABASE_URL}/rest/v1/analyses?select=*&order=created_at.desc&limit=50"
        response = requests.get(url, headers=headers)

        if response.status_code == 200:
            return jsonify(response.json())
        else:
            print(f"[history] Supabase error: {response.status_code} {response.text}")
            return jsonify([])
    except Exception as e:
        print(f"[history] Error fetching history: {e}")
        return jsonify([])


def save_to_supabase(result):
    """Save analysis result to Supabase analyses table."""
    if not SUPABASE_URL or not SUPABASE_ANON_KEY:
        return

    try:
        # Extract data from result
        meta = result.get("meta", {})
        stats = result.get("stats", {})
        signals = result.get("signals", [])

        payload = {
            "business_name": meta.get("business_name"),
            "address": meta.get("address"),
            "category": meta.get("category"),
            "google_rating": stats.get("google_rating"),
            "ai_rating": stats.get("ai_rating"),
            "trust_level": stats.get("trust_level"),
            "trust_label": stats.get("trust_label"),
            "suspicious_pct": stats.get("suspicious_pct"),
            "genuine_pct": stats.get("genuine_pct"),
            "uncertain_pct": stats.get("uncertain_pct"),
            "total_google": stats.get("total_google"),
            "signals": signals,
        }

        headers = {
            "apikey": SUPABASE_ANON_KEY,
            "Authorization": f"Bearer {SUPABASE_ANON_KEY}",
            "Content-Type": "application/json",
            "Prefer": "return=minimal",
        }

        url = f"{SUPABASE_URL}/rest/v1/analyses"
        response = requests.post(url, json=payload, headers=headers)

        if response.status_code not in (200, 201):
            print(f"[save_to_supabase] Error: {response.status_code} {response.text}")
    except Exception as e:
        print(f"[save_to_supabase] Exception: {e}")


def _sanitize(obj):
    """Recursively convert non-JSON-serializable objects to strings."""
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
