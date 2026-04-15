"""
RevBusters – HTML Card Generator
Takes an analysis dict (from analyze_reviews.analyze()) and returns an HTML string.
"""

import urllib.parse


WHATSAPP_SVG = """<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
        <path d="M17.472 14.382c-.297-.149-1.758-.867-2.03-.967-.273-.099-.471-.148-.67.15-.197.297-.767.966-.94 1.164-.173.199-.347.223-.644.075-.297-.15-1.255-.463-2.39-1.475-.883-.788-1.48-1.761-1.653-2.059-.173-.297-.018-.458.13-.606.134-.133.298-.347.446-.52.149-.174.198-.298.298-.497.099-.198.05-.371-.025-.52-.075-.149-.669-1.612-.916-2.207-.242-.579-.487-.5-.669-.51-.173-.008-.371-.01-.57-.01-.198 0-.52.074-.792.372-.272.297-1.04 1.016-1.04 2.479 0 1.462 1.065 2.875 1.213 3.074.149.198 2.096 3.2 5.077 4.487.709.306 1.262.489 1.694.625.712.227 1.36.195 1.871.118.571-.085 1.758-.719 2.006-1.413.248-.694.248-1.289.173-1.413-.074-.124-.272-.198-.57-.347m-5.421 7.403h-.004a9.87 9.87 0 01-5.031-1.378l-.361-.214-3.741.982.998-3.648-.235-.374a9.86 9.86 0 01-1.51-5.26c.001-5.45 4.436-9.884 9.888-9.884 2.64 0 5.122 1.03 6.988 2.898a9.825 9.825 0 012.893 6.994c-.003 5.45-4.437 9.884-9.885 9.884m8.413-18.297A11.815 11.815 0 0012.05 0C5.495 0 .16 5.335.157 11.892c0 2.096.547 4.142 1.588 5.945L.057 24l6.305-1.654a11.882 11.882 0 005.683 1.448h.005c6.554 0 11.89-5.335 11.893-11.893a11.821 11.821 0 00-3.48-8.413Z"/>
      </svg>"""

CSS = """
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      background: #f0f2f5;
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
      display: flex;
      justify-content: center;
      align-items: center;
      min-height: 100vh;
      padding: 24px 16px;
    }

    .card {
      background: #fff;
      border-radius: 16px;
      max-width: 400px;
      width: 100%;
      overflow: hidden;
      box-shadow: 0 4px 24px rgba(0,0,0,0.10);
    }

    .card-header { padding: 20px 24px 18px; background: #FF3B30; color: #fff; }
    .card-header.genuine    { background: #34C759; }
    .card-header.suspicious { background: #FF9500; }
    .card-header.fake       { background: #FF3B30; }

    .trust-badge {
      display: inline-flex; align-items: center; gap: 6px;
      font-size: 12px; font-weight: 700; letter-spacing: 0.8px;
      text-transform: uppercase; opacity: 0.92; margin-bottom: 8px;
    }
    .trust-badge .dot {
      width: 7px; height: 7px; border-radius: 50%;
      background: rgba(255,255,255,0.85);
    }
    .business-name { font-size: 22px; font-weight: 700; line-height: 1.2; }
    .business-meta { font-size: 12px; opacity: 0.82; margin-top: 4px; }

    .ratings {
      display: flex; padding: 20px 24px; gap: 0;
      border-bottom: 1px solid #f0f0f0;
    }
    .rating-item { flex: 1; text-align: center; }
    .rating-item + .rating-item { border-left: 1px solid #f0f0f0; }
    .rating-label {
      font-size: 11px; color: #8e8e93; font-weight: 600;
      letter-spacing: 0.4px; text-transform: uppercase; margin-bottom: 6px;
    }
    .rating-value { font-size: 28px; font-weight: 700; color: #1c1c1e; line-height: 1; }
    .rating-value .star { color: #FF9500; font-size: 20px; }
    .rating-count { font-size: 11px; color: #8e8e93; margin-top: 4px; }
    .rating-item.ai .rating-value { color: #FF3B30; }
    .rating-item.ai.ok .rating-value { color: #34C759; }

    .reasons { padding: 20px 24px; border-bottom: 1px solid #f0f0f0; }
    .reasons-title {
      font-size: 12px; font-weight: 700; color: #8e8e93;
      text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 14px;
    }
    .reason-item {
      display: flex; gap: 12px; margin-bottom: 14px; align-items: flex-start;
    }
    .reason-item:last-child { margin-bottom: 0; }
    .reason-icon {
      width: 28px; height: 28px; border-radius: 8px;
      background: #fff1f0; display: flex; align-items: center;
      justify-content: center; font-size: 14px; flex-shrink: 0; margin-top: 1px;
    }
    .reason-text { font-size: 13.5px; color: #3a3a3c; line-height: 1.5; }
    .reason-text strong { color: #1c1c1e; }

    .disclaimer {
      padding: 14px 24px; font-size: 11px; color: #aeaeb2;
      line-height: 1.5; border-bottom: 1px solid #f0f0f0;
    }

    .footer {
      padding: 16px 24px; display: flex; align-items: center;
      justify-content: space-between; gap: 12px;
    }
    .brand { font-size: 12px; font-weight: 700; color: #aeaeb2; letter-spacing: 0.3px; }
    .brand span { color: #FF3B30; }

    .whatsapp-btn {
      display: inline-flex; align-items: center; gap: 7px;
      background: #25D366; color: #fff; font-size: 13px; font-weight: 600;
      padding: 9px 16px; border-radius: 50px; text-decoration: none;
      border: none; cursor: pointer; transition: background 0.15s;
    }
    .whatsapp-btn:hover { background: #1ebe5c; }
    .whatsapp-btn svg { width: 16px; height: 16px; fill: #fff; flex-shrink: 0; }
"""


def _short_location(address: str) -> str:
    if not address:
        return ""
    parts = [p.strip() for p in address.split(",")]
    # Return last two meaningful parts (typically area + city)
    meaningful = [p for p in parts if p and not p.isdigit() and len(p) > 2]
    return ", ".join(meaningful[-2:]) if len(meaningful) >= 2 else meaningful[-1] if meaningful else address


def generate_card(result: dict, output_path: str = None) -> str:
    meta           = result["meta"]
    business_name  = meta.get("business_name") or "Unknown Business"
    address        = meta.get("address") or ""
    location       = _short_location(address)

    trust_level    = result["trust_level"]
    trust_label    = result["trust_label"]
    google_rating  = result["google_rating"]
    ai_rating      = result["ai_rating"]
    total_google   = result["total_google"]
    est_genuine    = result["estimated_genuine"]
    signals        = result["signals"]

    # AI column CSS class
    ai_cls = "rating-item ai ok" if trust_level == "genuine" else "rating-item ai"

    # Signals HTML
    signals_html = ""
    if signals:
        for s in signals:
            # Bold title, rest is detail
            detail_html = s["detail"].replace("<", "&lt;").replace(">", "&gt;")
            signals_html += f"""
    <div class="reason-item">
      <div class="reason-icon">{s['icon']}</div>
      <div class="reason-text">
        <strong>{s['title']}</strong> — {detail_html}
      </div>
    </div>"""
    else:
        signals_html = """
    <div class="reason-item">
      <div class="reason-icon">✅</div>
      <div class="reason-text">
        <strong>No major signals detected</strong> — review patterns appear consistent with genuine activity.
      </div>
    </div>"""

    # WhatsApp share
    fake_pct = max(0, round((1 - est_genuine / total_google) * 100)) if total_google else 0
    wa_text = (
        f"Check this fake review analysis for {business_name}: "
        f"Google says {google_rating}\u2605 but AI predicts {ai_rating}\u2605 "
        f"with {fake_pct}% suspicious reviews. revbusters.in"
    )
    wa_url = f"https://wa.me/?text={urllib.parse.quote(wa_text)}"

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>RevBusters – {business_name}</title>
  <style>{CSS}
  </style>
</head>
<body>

<div class="card">

  <!-- Header -->
  <div class="card-header {trust_level}">
    <div class="trust-badge"><span class="dot"></span> {trust_label}</div>
    <div class="business-name">{business_name}</div>
    <div class="business-meta">{location}</div>
  </div>

  <!-- Ratings -->
  <div class="ratings">
    <div class="rating-item">
      <div class="rating-label">Google Rating</div>
      <div class="rating-value"><span class="star">★</span> {google_rating}</div>
      <div class="rating-count">{total_google:,} reviews</div>
    </div>
    <div class="{ai_cls}">
      <div class="rating-label">AI Predicted</div>
      <div class="rating-value"><span class="star">★</span> {ai_rating}</div>
      <div class="rating-count">~{est_genuine:,} genuine reviews</div>
    </div>
  </div>

  <!-- Signals -->
  <div class="reasons">
    <div class="reasons-title">Signals detected</div>
    {signals_html}
  </div>

  <!-- Disclaimer -->
  <div class="disclaimer">
    Algorithmic estimate only — indicates suspicious patterns, not a definitive conclusion.
    We recommend reading reviews directly before deciding.
  </div>

  <!-- Footer -->
  <div class="footer">
    <div class="brand"><span>Rev</span>Busters</div>
    <a class="whatsapp-btn" href="{wa_url}" target="_blank">
      {WHATSAPP_SVG}
      Share on WhatsApp
    </a>
  </div>

</div>

</body>
</html>"""

    if output_path:
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(html)

    return html


if __name__ == "__main__":
    import sys, json
    path = sys.argv[1] if len(sys.argv) > 1 else "analysis_output.json"
    with open(path, encoding="utf-8") as f:
        result = json.load(f)
    out = sys.argv[2] if len(sys.argv) > 2 else "card_output.html"
    generate_card(result, output_path=out)
    print(f"Card saved → {out}")
