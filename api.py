"""
RevBusters – Flask API
Endpoints:
  GET  /ping     → warmup / health check
  POST /analyze  → { "url": "..." } → analysis JSON
"""

import os
import json
import traceback
from flask import Flask, request, jsonify
from flask_cors import CORS
from dotenv import load_dotenv

from scrape_reviews import scrape_reviews
from analyze_reviews import analyze

load_dotenv()

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})

@app.after_request
def add_cors_headers(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    return response

@app.route("/analyze", methods=["OPTIONS"])
def analyze_preflight():
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

        # Make result JSON-safe (remove datetime objects etc.)
        return jsonify(_sanitize(result))

    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


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
