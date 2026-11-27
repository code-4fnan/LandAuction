"""Marketplace: hero, live stats, and every parcel as satellite cards or on a map."""

from __future__ import annotations

import folium
import streamlit as st
from streamlit_folium import st_folium

from landauction import geo, services

from . import ui
from .common import (
    PAGES, STATUS_META, add_parcels, base_map, current_user, db, money_compact, open_room,
    parcel_at, time_left_label,
)

SORTS = {
    "Ending soonest": "ending",
    "Newest listings": "newest",
    "Highest price": "price_high",
    "Lowest price": "price_low",
    "Most bids": "bids",
}
STATUSES = {"Live now": "active", "All": "all", "Closed": "ended"}
HERO_CENTER = (12.95, 77.54)  # puts the Bengaluru demo parcels in the hero's clear right-hand side


def render() -> None:
    with db() as s:
        stats = services.market_stats(s)
        everything = services.list_parcels(s, status="active")
        st.session_state["_photo_counts"] = services.photo_counts(s)
    _hero(stats, everything)

    ui.section("Browse land", kicker="Marketplace")
    f1, f2, f3, f4 = st.columns([2.6, 1.6, 1.4, 1.1], vertical_alignment="center")
    search = f1.text_input("Search", placeholder="Search by name, locality or keyword…",
                           label_visibility="collapsed", icon=":material/search:")
    status = f2.segmented_control("Status", list(STATUSES), default="Live now", label_visibility="collapsed")
    sort = f3.selectbox("Sort", list(SORTS), label_visibility="collapsed")
    view = f4.segmented_control("View", ["Grid", "Map"], default="Grid", label_visibility="collapsed",
                                key="market_view")

    with db() as s:
        parcels = services.list_parcels(
            s, search=search, status=STATUSES.get(status or "All", "all"), sort=SORTS[sort]
        )

    if not parcels:
        st.info("No parcels match those filters. Try clearing the search, or list your own land.",
                icon=":material/travel_explore:")
        return

    st.html(f'<div class="la-section-aside">{len(parcels)} parcel{"s" if len(parcels) != 1 else ""}</div>')
    if view == "Map":
        _map_view(parcels)
    else:
        _grid(parcels)


def _hero(stats: services.MarketStats, live: list) -> None:
    dots = [(p.centroid_lat, p.centroid_lng) for p in live]
    imagery = ui.satellite(width=1600, height=800, center=HERO_CENTER, zoom=12, dots=dots, outline=False)
    tiles = ui.stat_tiles([
        (str(stats.active), "Live auctions", f"{stats.ending_soon} closing within the hour"),
        (money_compact(stats.active_value), "Total bids in play", ""),
        (f"{stats.total_bids:,}", "Bids placed", f"by {stats.bidders} bidders"),
        ("2 min", "Anti-snipe window", "late bids extend the clock"),
    ], dark=True)
    st.html(f"""
<section class="la-hero">
  {imagery}
  <div class="la-hero-content">
    <div class="la-eyebrow">● Live auctions</div>
    <h1>Bid on land you can <em>see</em>, in real time.</h1>
    <p>Every parcel is traced on satellite imagery, priced in the open and sold to the highest bidder.
       You see every rival bid the moment it's placed.</p>
    {tiles}
  </div>
</section>""")
    c1, c2, _ = st.columns([1.2, 1.2, 4])
    if c1.button("Browse live auctions", type="primary", icon=":material/arrow_downward:", width="stretch"):
        st.session_state["market_view"] = "Grid"
    if c2.button("Sell your land", icon=":material/add_location_alt:", width="stretch"):
        st.switch_page(PAGES["sell"])
    if not current_user():
        st.caption("Browsing as a guest. Use **Sign in** (top right) to bid, or try the demo account.")


def _grid(parcels: list) -> None:
    cols = st.columns(3, gap="medium")
    for i, p in enumerate(parcels):
        with cols[i % 3]:
            _card(p)


def _card(p, key_prefix: str = "pcard") -> None:
    with st.container(key=f"{key_prefix}_{p.id}"):
        n_photos = st.session_state.get("_photo_counts", {}).get(p.id, 0)
        st.html(ui.parcel_card_html(p, price=money_compact(p.current_price), time_left=time_left_label(p),
                                    photos=n_photos))
        ended = services.parcel_status(p) == "ended"
        go, pics = st.columns([1.55, 1])
        if go.button("View results" if ended else "Open auction", key=f"open_{key_prefix}_{p.id}",
                     type="secondary" if ended else "primary", width="stretch",
                     icon=":material/insights:" if ended else ":material/gavel:"):
            open_room(p.id)
        if pics.button("Photos", key=f"pics_{key_prefix}_{p.id}", icon=":material/photo_library:",
                       width="stretch", help="See photos and aerial views of this property"):
            _quick_view(p.id)


@st.dialog("Property photos & views", width="large")
def _quick_view(parcel_id: int) -> None:
    with db() as s:
        p = services.get_parcel(s, parcel_id)
        photos = services.list_photos(s, parcel_id)
    if p is None:
        st.error("This listing no longer exists.")
        return
    st.html(f'<div class="la-loc">{ui.esc(p.location) or "Location not given"}</div>'
            f'<div class="la-card-title" style="font-size:1.7rem">{ui.esc(p.title)}</div>')
    st.html(ui.gallery(p, photos, key=f"dlg{p.id}"))
    if not photos:
        st.caption("The seller hasn't uploaded photos yet. These are aerial views of the exact plot.")
    if st.button("Enter auction room", type="primary", icon=":material/gavel:", width="stretch"):
        open_room(p.id)


def _map_view(parcels: list) -> None:
    map_col, side_col = st.columns([2.2, 1], gap="medium")
    selected_id = st.session_state.get("market_selected")
    with map_col:
        m = base_map(satellite=True)
        rings = add_parcels(m, parcels, highlight_id=selected_id)
        m.fit_bounds(geo.bounds(rings), padding=(30, 30), max_zoom=16)
        folium.LayerControl(collapsed=True).add_to(m)
        result = st_folium(m, key="market_map", height=620, use_container_width=True,
                           returned_objects=["last_object_clicked"])
        legend = " &nbsp;&nbsp; ".join(
            f"<span style='color:{color};font-size:1.1em'>●</span> {label}"
            for label, _, color in STATUS_META.values()
        )
        st.html(f"<div class='la-note'>{legend} &nbsp;&nbsp;·&nbsp;&nbsp; Click a parcel to preview it</div>")

        clicked = (result or {}).get("last_object_clicked")
        if clicked:
            hit = parcel_at(parcels, clicked["lat"], clicked["lng"])
            if hit and hit.id != selected_id:
                st.session_state["market_selected"] = hit.id
                st.rerun()

    with side_col:
        selected = next((p for p in parcels if p.id == selected_id), None) or parcels[0]
        st.html('<div class="la-kicker">Selected parcel</div>')
        _card(selected, key_prefix="pcard_sel")
