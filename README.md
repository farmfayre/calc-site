# Farm Fayre Calculator (calc.farmfayre.com)

Static site that lets affiliates compare today's mart trade against Farm Fayre's bid for cattle.

## How it works
- `index.html` — the calculator (single self-contained file)
- `market_data.json` — live mart pricing data, updated weekly by the VM scraper
- `fonts/` — vendored Carlito + Poppins (no Google Fonts dependency = clean PNG export)
- `logo.png` — Farm Fayre logo (transparent PNG)
- `html2canvas.min.js` — vendored library for PNG export

## Updating market data
The VM at `/opt/farmfayre/` runs `scraper.py` weekly via cron, which writes `market_data.json` here.
The cron job pushes this repo to GitHub, which Netlify auto-deploys to calc.farmfayre.com.

## Local testing
```
cd calc-site && python3 -m http.server 8000
# open http://localhost:8000/
```

## Deployment
- Repo: github.com/farmfayre/calc-site
- Hosting: Netlify (free tier)
- Domain: calc.farmfayre.com (CNAME at Blacknight)
