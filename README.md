# 🌍 LandAuction

**Real-time land auctions on a map, built with Streamlit.**

[![Open in Streamlit](https://static.streamlit.io/badges/streamlit_badge_black_white.svg)](https://landauction-skrywtozwgts399ljeegtj.streamlit.app)

**🔗 Live demo: [landauction-skrywtozwgts399ljeegtj.streamlit.app](https://landauction-skrywtozwgts399ljeegtj.streamlit.app)**:
click **Sign in → Explore with the demo account** to start bidding straight away.

Sellers trace a parcel's boundary on a satellite map and start a timed auction. Buyers
browse parcels on the map, open a live auction room, and bid against each other. The room
updates every few seconds, so rival bids appear without a page reload.

> ⚠️ Portfolio project. No real money or property changes hands.

## Features

| | |
| --- | --- |
| **Satellite-first design** | Every listing card and auction room shows real satellite imagery of the plot with its surveyed boundary drawn on top. |
| **Property gallery** | Click **Photos** on any card, or open the auction room, to flip through the seller's uploaded photos plus generated views of the exact plot: aerial close-up, tilted bird's-eye views from two angles, neighbourhood, area context and street map. Uploads are validated, resized and stripped of location data. |
| **Map marketplace** | All parcels on one map, colour-coded *live / ending soon / ended*. Search, filter, sort, and click a parcel to select it. |
| **Draw to list** | Trace a polygon or rectangle on street or satellite tiles. The geodesic area (sq ft / acres / hectares) is calculated as you draw. |
| **Live auction room** | Current price, a ticking countdown, quick-bid buttons, a custom-bid form, a price-history chart and a bid log, all refreshing automatically. You get a toast when someone outbids you. |
| **Fair bidding rules** | Minimum increments. Sellers can't bid on their own land and leaders can't raise their own bid. **Anti-sniping:** a late bid extends the auction. |
| **Race-safe bids** | Each bid is a single conditional `UPDATE`, so two people bidding at the same moment can never both win (covered by a concurrency test). |
| **Accounts** | Registration and login with bcrypt-hashed passwords, plus a one-click demo account. |
| **My activity** | Your bids (winning / outbid / won / lost), your listings and your watchlist. Click a row to open its auction room. |
| **Zero infrastructure** | SQLite by default: no Docker, Postgres or Redis. Optionally point it at hosted Postgres. |

## Quick start (local)

Requires Python 3.10+.

```bash
git clone https://github.com/code-4fnan/LandAuction.git
cd LandAuction

python -m venv venv
# Windows
venv\Scripts\activate
# macOS / Linux
source venv/bin/activate

pip install -r requirements.txt
streamlit run streamlit_app.py
```

The app opens at http://localhost:8501. On first run it creates `data/landauction.db`
and fills it with demo parcels and bids. Click **Try the demo account** in the sidebar,
or register your own account. Demo users all have the password `demo1234`:
`demo`, `priya_estates`, `rahul_k`, `greenacres` and `meera_s`.

**Try live bidding:** open the same auction in two browser windows, log in as different
users, and bid. Each window picks up the other's bids within a few seconds.

## Deploy to Streamlit Community Cloud (free)

1. Push this repository to GitHub.
2. Go to [share.streamlit.io](https://share.streamlit.io), choose **Create app → Deploy a public app from GitHub**,
   and pick this repo, the branch, and `streamlit_app.py` as the main file.
3. Under **Advanced settings**, choose Python 3.12. Optionally paste settings from
   [`.streamlit/secrets.toml.example`](.streamlit/secrets.toml.example) into **Secrets**.
4. Click **Deploy**.

### Keeping data between restarts

Streamlit Cloud's disk is temporary. With the default SQLite file, data resets whenever the
app restarts or redeploys, and a fresh demo dataset is seeded. That's fine for a demo. For
data that persists:

1. Create a free Postgres database (e.g. [Neon](https://neon.tech) or [Supabase](https://supabase.com)).
2. Uncomment `psycopg[binary]` in `requirements.txt`.
3. Add it to the app's **Secrets**:
   ```toml
   DATABASE_URL = "postgresql+psycopg://user:password@host/dbname?sslmode=require"
   ```

Tables are created automatically on first start.

## Configuration

Each setting can come from an environment variable or from Streamlit secrets.

| Setting | Default | Purpose |
| --- | --- | --- |
| `DATABASE_URL` | `sqlite:///data/landauction.db` | Any SQLAlchemy URL (SQLite or Postgres). |
| `APP_TIMEZONE` | `Asia/Kolkata` | Timezone used to display auction times. |
| `CURRENCY_SYMBOL` | `₹` | `₹` uses Indian digit grouping (1,23,45,678). |
| `SEED_DEMO_DATA` | `true` | Seed demo data into an empty database and show the demo-login button. |
| `ANTI_SNIPE_SECONDS` | `120` | A bid this close to the end pushes the end time back by this much. |
| `MAX_AUCTION_DAYS` | `60` | Longest allowed auction. |
| `REFRESH_SECONDS` | `3` | How often auction rooms poll for new bids. |

## Project structure

```text
├── streamlit_app.py         # Entry point: top navigation, account menu, footer
├── assets/                  # style.css design system, logo
├── app_pages/               # One module per page (UI only)
│   ├── common.py            #   shared helpers: DB session, auth state, maps, formatting
│   ├── ui.py                #   satellite thumbnails, cards, pills, live countdown
│   ├── marketplace.py       #   map + filterable list of parcels
│   ├── room.py              #   live auction room (auto-refreshing fragments)
│   ├── sell.py              #   draw a boundary and create a listing
│   ├── activity.py          #   my bids / listings / watchlist
│   └── about.py             #   how it works
├── landauction/             # Core logic, no Streamlit dependency
│   ├── config.py            #   settings from env / secrets
│   ├── db.py                #   SQLAlchemy models + engine/session
│   ├── services.py          #   auth, listings, atomic bidding, activity queries
│   ├── geo.py               #   polygon validation, geodesic area, point-in-polygon
│   ├── images.py            #   photo validation / resizing / EXIF stripping
│   ├── fmt.py               #   money / time formatting
│   └── seed.py              #   demo data
├── tests/test_core.py       # pytest suite for the business rules
├── .streamlit/config.toml   # theme
└── requirements.txt
```

## How it works

```mermaid
graph LR
    A[Browser] -->|Streamlit websocket| B[streamlit_app.py<br/>pages + fragments]
    B --> C[landauction.services<br/>rules + atomic bids]
    C --> D[(SQLite / Postgres)]
    B -. polls every few s .-> C
```

- **Real-time updates:** the auction room's price panel and bid history are
  [`st.fragment`](https://docs.streamlit.io/develop/api-reference/execution-flow/st.fragment)s
  with `run_every`, so only those parts re-run, every few seconds.
- **Atomic bidding:** `place_bid` runs `UPDATE parcels SET … WHERE id = ? AND end_time > now
  AND <amount meets minimum> AND <bidder isn't seller or leader>` and checks the row count.
  The database serialises concurrent writers, so the second of two identical bids fails
  that check and gets a clear "bid too low" message.
- **Geometry:** boundaries are stored as GeoJSON. Area uses the same spherical-excess
  formula as Turf.js, so no PostGIS or GDAL is needed.

## Running tests

```bash
pip install -r requirements-dev.txt
pytest
```

## Tech stack

Streamlit · Esri World Imagery · streamlit-folium / Leaflet (maps and drawing) · SQLAlchemy 2 · SQLite or Postgres ·
bcrypt · Plotly · pandas

## Roadmap

- [ ] Persistent login across browser refreshes (signed cookie)
- [ ] Email notifications when you're outbid or win
- [ ] Image uploads for parcels
- [ ] Virtual wallet with deposits required before bidding

## License

MIT
