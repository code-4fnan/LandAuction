"""Sell land: draw a boundary on the map and start an auction."""

from __future__ import annotations

from datetime import datetime, time, timedelta

import folium
import streamlit as st
from folium.plugins import Draw, LocateControl
from streamlit_folium import st_folium

from landauction import fmt, geo, services
from landauction.config import settings
from landauction.db import utcnow

from . import ui
from .common import save_photos, add_parcels, base_map, db, flash, local_time, money, open_room, require_login

CITIES = {
    "Bengaluru": (12.9716, 77.5946),
    "Mumbai": (19.0760, 72.8777),
    "Delhi": (28.6139, 77.2090),
    "Hyderabad": (17.3850, 78.4867),
    "Chennai": (13.0827, 80.2707),
    "Pune": (18.5204, 73.8567),
    "Kolkata": (22.5726, 88.3639),
    "Custom coordinates": None,
}
DURATIONS = {"1 hour": 1, "6 hours": 6, "1 day": 24, "3 days": 72, "7 days": 168, "Custom": None}


def render() -> None:
    ui.section("List your land for auction", kicker="Sell land",
               aside="Free to list · Buyers bid live · You see every bid")
    user = require_login("list a property")
    steps_slot = st.empty()

    c1, c2, c3 = st.columns([2, 2, 1.2], vertical_alignment="bottom")
    city = c1.selectbox("Jump to", list(CITIES))
    center = CITIES[city]
    if center is None:
        lat = c2.number_input("Latitude", value=12.9716, format="%.5f", min_value=-90.0, max_value=90.0)
        lng = c3.number_input("Longitude", value=77.5946, format="%.5f", min_value=-180.0, max_value=180.0)
        center = (lat, lng)
    else:
        c2.caption("Use the satellite layer (top right) to trace field edges.")

    with db() as s:
        existing = services.list_parcels(s, status="active")

    m = base_map(center=center, zoom=15, satellite=True)
    add_parcels(m, existing, muted=True)
    Draw(
        export=False,
        position="topleft",
        draw_options={
            "polyline": False, "circle": False, "marker": False, "circlemarker": False,
            "polygon": {"allowIntersection": False, "showArea": True,
                        "shapeOptions": {"color": "#2e7d32"}},
            "rectangle": {"shapeOptions": {"color": "#2e7d32"}},
        },
        edit_options={"edit": True, "remove": True},
    ).add_to(m)
    LocateControl(position="topleft", strings={"title": "Show my location"}).add_to(m)
    folium.LayerControl(collapsed=True).add_to(m)

    result = st_folium(m, key=f"draw_map_{center}", height=520, use_container_width=True,
                       returned_objects=["all_drawings"])
    drawings = [d for d in (result or {}).get("all_drawings") or []
                if (d.get("geometry") or {}).get("type") == "Polygon"]

    _steps(steps_slot, 2 if drawings else 1)
    if not drawings:
        st.info("Use the **polygon** or **rectangle** tool on the left of the map to outline your parcel. "
                "Grey shapes are parcels already up for auction.", icon=":material/draw:")
        return

    geometry = drawings[-1]["geometry"]
    if len(drawings) > 1:
        st.caption("You drew more than one shape. The most recent one will be used.")
    try:
        ring = geo.outer_ring(geometry)
    except geo.GeometryError as exc:
        st.error(str(exc))
        return
    area = geo.ring_area_sqm(ring)
    st.success(f"Boundary captured: **{geo.format_area(area)}**", icon=":material/check_circle:")

    _listing_form(user, geometry)


def _listing_form(user: dict, geometry: dict) -> None:
    sym = settings.currency_symbol
    with st.form("new_listing"):
        st.subheader("Listing details")
        title = st.text_input("Title *", max_chars=120, placeholder="e.g. 2-acre farmland near Hosur")
        location = st.text_input("Area / locality", max_chars=120, placeholder="e.g. Hosur Road, Bengaluru")
        description = st.text_area("Description", max_chars=2000,
                                   placeholder="Access road, zoning, approvals, water, title status…")

        p1, p2 = st.columns(2)
        start = p1.number_input(f"Starting price ({sym}) *", min_value=1, value=1_000_000,
                                step=10_000, format="%d")
        increment = p2.number_input(f"Minimum bid increment ({sym}) *", min_value=1, value=10_000,
                                    step=1_000, format="%d")

        d1, d2, d3 = st.columns([2, 1.5, 1.5])
        duration = d1.radio("Auction length", list(DURATIONS), index=3, horizontal=True)
        tomorrow = fmt.to_local(utcnow() + timedelta(days=1), settings.timezone)
        end_date = d2.date_input("Custom end date", value=tomorrow.date(),
                                 min_value=tomorrow.date() - timedelta(days=1))
        end_clock = d3.time_input("Custom end time", value=time(18, 0))
        st.caption(f"Custom date and time are used only when **Custom** is selected. Times are in {settings.timezone}.")

        uploads = st.file_uploader(
            f"Photos (optional, up to {services.MAX_PHOTOS})", type=["jpg", "jpeg", "png", "webp"],
            accept_multiple_files=True,
            help="Ground-level photos help buyers: the entrance, road access, boundary markers, views. "
                 "Location data is stripped from uploads.",
        )

        submitted = st.form_submit_button("Start auction", type="primary", icon=":material/rocket_launch:")

    if not submitted:
        return

    hours = DURATIONS[duration]
    if hours is None:
        end_time = fmt.local_to_utc(datetime.combine(end_date, end_clock), settings.timezone)
    else:
        end_time = utcnow() + timedelta(hours=hours)

    try:
        with db() as s:
            parcel = services.create_parcel(
                s, seller_id=user["id"], title=title, description=description, location=location,
                geometry=geometry, starting_price=int(start), min_increment=int(increment),
                end_time=end_time, max_days=settings.max_auction_days,
            )
            new_id, ends = parcel.id, parcel.end_time
    except services.ValidationError as exc:
        st.error(str(exc))
        return

    saved, errors = save_photos(new_id, user["id"], (uploads or [])[: services.MAX_PHOTOS])
    for err in errors:
        flash("error", err)
    photo_note = f" {saved} photo{'s' if saved != 1 else ''} added." if saved else ""
    flash("success", f"Auction started at {money(start)}. It ends {local_time(ends)}.{photo_note}")
    open_room(new_id)


def _steps(slot, current: int) -> None:
    items = [
        ("Find the land", "Jump to a city, then zoom in on satellite imagery"),
        ("Trace the boundary", "Use the polygon or rectangle tool on the map"),
        ("Set your terms", "Starting price, increment and auction length"),
    ]
    cells = "".join(
        f'<div class="la-step {"done" if i < current else "now" if i == current else ""}">'
        f'<div class="la-step-n">{"✓" if i < current else i + 1}</div>'
        f'<div><div class="la-step-t">{t}</div><div class="la-step-s">{d}</div></div></div>'
        for i, (t, d) in enumerate(items)
    )
    slot.html(f'<div class="la-steps">{cells}</div>')
