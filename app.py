import os
import time
import requests
from flask import Flask, make_response, render_template_string

# --- Config via variables d'environnement ---
NOTION_TOKEN = os.environ.get("NOTION_TOKEN", "")
DATABASE_ID  = os.environ.get("DATABASE_ID", "")
LEVEL_XP     = int(os.environ.get("LEVEL_XP", "200"))  # XP par niveau
CACHE_TTL    = int(os.environ.get("CACHE_TTL", "120")) # secondes

if not NOTION_TOKEN or not DATABASE_ID:
    raise RuntimeError("Env vars NOTION_TOKEN et DATABASE_ID sont requises.")

headers = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28",
}

app = Flask(__name__)

# --- Cache très simple pour limiter les appels API Notion ---
_cache = {"ts": 0, "payload": None}

def fetch_all_pages():
    url = f"https://api.notion.com/v1/databases/{DATABASE_ID}/query"
    payload = {"page_size": 100}
    results = []
    while True:
        res = requests.post(url, json=payload, headers=headers, timeout=20)
        res.raise_for_status()
        data = res.json()
        results.extend(data.get("results", []))
        if data.get("has_more") and data.get("next_cursor"):
            payload["start_cursor"] = data["next_cursor"]
        else:
            break
    return results

def compute_xp_level_progress():
    # Cache (évite de toucher l'API à chaque refresh de l’embed)
    now = time.time()
    if _cache["payload"] and now - _cache["ts"] < CACHE_TTL:
        results = _cache["payload"]
    else:
        results = fetch_all_pages()
        _cache["payload"] = results
        _cache["ts"] = now

    # Additionne l'XP (que ta propriété "XP" soit "number" ou "formula")
    xp_tot = 0
    for page in results:
        props = page.get("properties", {})
        xp_prop = props.get("XP", {})
        xp_val = 0
        t = xp_prop.get("type")
        if t == "number":
            xp_val = xp_prop.get("number") or 0
        elif t == "formula":
            # handle number formulas
            xp_val = (xp_prop.get("formula") or {}).get("number") or 0
        xp_tot += xp_val

    level = xp_tot // LEVEL_XP
    reste = xp_tot % LEVEL_XP
    progress = (reste / LEVEL_XP) * 100.0
    return xp_tot, level, progress

@app.route("/health")
def health():
    return {"ok": True}

@app.route("/")
def index():
    try:
        xp_tot, level, progress = compute_xp_level_progress()
    except Exception as e:
        # Affiche une erreur lisible dans l’embed en cas de souci
        html_err = f"""
        <html><body style="background:#111;color:#eee;font-family:system-ui;padding:24px">
          <h3>Erreur widget</h3>
          <p>{str(e)}</p>
          <p>Vérifie NOTION_TOKEN / DATABASE_ID et que l'intégration a accès à la base.</p>
        </body></html>
        """
        resp = make_response(html_err, 500)
        resp.headers["Cache-Control"] = "no-store"
        return resp

    # SVG cercle + auto-refresh (toutes les 5 min)
    # stroke-dasharray = progress, 100 (sur ce type de cercle)
    html = f"""
    <html>
    <head>
      <meta charset="utf-8" />
      <meta name="viewport" content="width=device-width, initial-scale=1" />
      <meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate" />
      <meta http-equiv="Pragma" content="no-cache" />
      <meta http-equiv="Expires" content="0" />
      <script>
        // Recharge l’embed toutes les 5 minutes pour récupérer les nouvelles données
        setInterval(function() {{
          window.location.reload();
        }}, 5 * 60 * 1000);
      </script>
      <style>
        html, body {{
          height: 100%;
          background: #0f1226;
          color: #eaf0ff;
          margin: 0;
          font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Arial, "Apple Color Emoji","Segoe UI Emoji";
        }}
        .wrap {{
          height: 100%;
          display: flex;
          align-items: center;
          justify-content: center;
          gap: 18px;
          flex-direction: column;
          padding: 16px;
        }}
        .title {{ font-weight: 600; opacity: .9; }}
        .meta {{ opacity: .8; font-size: 14px; }}
        svg {{ filter: drop-shadow(0 6px 16px rgba(0,0,0,.4)); }}
        .track {{ stroke: #2a2f58; }}
        .bar {{
          stroke: #7aa2ff;
          transition: stroke-dasharray 1s ease-out;
        }}
      </style>
    </head>
    <body>
      <div class="wrap">
        <div class="title">Morning Routine — Progression du niveau</div>
        <svg viewBox="0 0 36 36" width="180" height="180">
          <!-- cercle de fond -->
          <path class="track"
            d="M18 2.0845
               a 15.9155 15.9155 0 0 1 0 31.831
               a 15.9155 15.9155 0 0 1 0 -31.831"
            fill="none" stroke-width="2"/>
          <!-- progression -->
          <path class="bar"
            d="M18 2.0845
               a 15.9155 15.9155 0 0 1 0 31.831
               a 15.9155 15.9155 0 0 1 0 -31.831"
            fill="none" stroke-width="2"
            stroke-dasharray="{progress:.2f}, 100" />
          <!-- niveau au centre -->
          <text x="18" y="19.5" fill="#eaf0ff" font-size="5" text-anchor="middle" style="font-weight:700">
            Niv {level}
          </text>
          
        </svg>
        <div class="meta">{xp_tot} XP total • {LEVEL_XP} XP / niveau</div>
      </div>
    </body>
    </html>
    """
    resp = make_response(render_template_string(html))
    # Désactive le cache côté CDN/iframe pour forcer la fraîcheur
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate, max-age=0"
    return resp

if __name__ == "__main__":
    # En local : http://localhost:5000
    app.run(host="0.0.0.0", port=5000, debug=True)
