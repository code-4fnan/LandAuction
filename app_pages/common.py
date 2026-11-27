"""Helpers shared by every page: DB access, auth state, formatting and maps."""

from __future__ import annotations

import html
import re
from typing import Any, Iterable

import folium
import streamlit as st

from landauction import fmt, geo, services
from landauction.config import settings
from landauction.db import Parcel, get_engine, session_scope, utcnow
from landauction.seed import seed_demo_data

DEFAULT_CENTER = (12.9716, 77.5946)  # Bengaluru

STATUS_META = {
    #  status        label          badge color  map color
    "live": ("Live", "green", "#22A06B"),
    "ending_soon": ("Ending soon", "orange", "#EA580C"),
    "ended": ("Closed", "gray", "#A8A29E"),
}

ESRI_SATELLITE = (
    "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
)

# Filled in by streamlit_app.py so pages can link to each other without circular imports.
PAGES: dict[str, st.Page] = {}


# ----------------------------------------------------------------------------- data


def db():
    return session_scope(settings.database_url)


@st.cache_resource(show_spinner="Preparing the database…")
def init_database() -> bool:
    get_engine(settings.database_url)
    if settings.seed_demo_data:
        with db() as s:
            seed_demo_data(s, settings.anti_snipe_seconds)
    return True


# ----------------------------------------------------------------------------- auth


def current_user() -> dict[str, Any] | None:
    return st.session_state.get("user")


def sign_in(user) -> None:
    st.session_state["user"] = {"id": user.id, "username": user.username}


def sign_out() -> None:
    for key in ("user", "seen_bids"):
        st.session_state.pop(key, None)


def require_login(action: str) -> dict[str, Any]:
    user = current_user()
    if user is None:
        st.info(f"Log in or create an account in the sidebar to {action}.", icon=":material/lock:")
        st.stop()
    return user


# ----------------------------------------------------------------------------- formatting


def money(n: int | float) -> str:
    return fmt.money(n, settings.currency_symbol)


def money_compact(n: int | float) -> str:
    return fmt.money_compact(n, settings.currency_symbol)


def local_time(dt) -> str:
    return fmt.local_str(dt, settings.timezone)


_MD_SPECIAL = re.compile(r"([\\`*_{}\[\]()#+\-.!|<>~$])")


def md(text: str) -> str:
    """Escape user text before putting it inside Markdown."""
    return _MD_SPECIAL.sub(r"\\\1", text or "")


def time_left_label(parcel: Parcel) -> str:
    remaining = (parcel.end_time - utcnow()).total_seconds()
    if remaining <= 0:
        return f"Ended {local_time(parcel.end_time)}"
    return f"{fmt.duration(remaining)} left"


def status_badge(parcel: Parcel) -> None:
    label, color, _ = STATUS_META[services.parcel_status(parcel)]
    st.badge(label, color=color)


def flash(kind: str, message: str) -> None:
    """Queue a toast to show on the next render (survives st.switch_page / reruns)."""
    st.session_state.setdefault("_flash", []).append((kind, message))


def show_flashes() -> None:
    icons = {"success": ":material/check_circle:", "error": ":material/error:", "info": ":material/info:"}
    for kind, message in st.session_state.pop("_flash", []):
        st.toast(message, icon=icons.get(kind))


def open_room(parcel_id: int) -> None:
    st.session_state["parcel_id"] = parcel_id
    st.switch_page(PAGES["room"], query_params={"parcel": str(parcel_id)})


def save_photos(parcel_id: int, user_id: int, files, caption: str = "") -> tuple[int, list[str]]:
    """Store uploaded files one by one; returns (saved count, error messages)."""
    saved, errors = 0, []
    for f in files or []:
        try:
            with db() as s:
                services.add_photo(s, parcel_id=parcel_id, user_id=user_id, raw=f.getvalue(), caption=caption)
            saved += 1
        except services.ValidationError as exc:
            errors.append(f"{f.name}: {exc}")
    return saved, errors


# ----------------------------------------------------------------------------- maps


def base_map(center: Iterable[float] = DEFAULT_CENTER, zoom: int = 12, satellite: bool = False) -> folium.Map:
    m = folium.Map(location=list(center), zoom_start=zoom, tiles=None, control_scale=True)
    street = folium.TileLayer("OpenStreetMap", name="Street map", show=not satellite)
    sat = folium.TileLayer(tiles=ESRI_SATELLITE, attr="Tiles © Esri", name="Satellite", show=satellite)
    # The layer added last is shown first unless `show` says otherwise.
    for layer in (street, sat):
        layer.add_to(m)
    return m


def add_parcels(m: folium.Map, parcels: Iterable[Parcel], highlight_id: int | None = None,
                muted: bool = False) -> list[geo.Ring]:
    rings = []
    for p in parcels:
        ring = services.parcel_ring(p)
        rings.append(ring)
        color = "#9ca3af" if muted else STATUS_META[services.parcel_status(p)][2]
        tooltip = (
            f"<b>{html.escape(p.title)}</b><br>{html.escape(p.location)}<br>"
            f"{money(p.current_price)} · {p.bid_count} bid{'s' if p.bid_count != 1 else ''}"
        )
        folium.Polygon(
            geo.latlngs(ring),
            color=color,
            weight=4 if p.id == highlight_id else 2,
            fill=True,
            fill_color=color,
            fill_opacity=0.12 if muted else 0.28,
            tooltip=tooltip,
        ).add_to(m)
        if not muted:
            folium.CircleMarker(
                [p.centroid_lat, p.centroid_lng], radius=6, color="white", weight=2,
                fill=True, fill_color=color, fill_opacity=1, tooltip=tooltip,
            ).add_to(m)
    return rings


def parcel_at(parcels: list[Parcel], lat: float, lng: float) -> Parcel | None:
    """Parcel containing a clicked point, else the nearest centre within ~300 m."""
    for p in parcels:
        if geo.point_in_ring(lng, lat, services.parcel_ring(p)):
            return p
    best = min(parcels, key=lambda p: (p.centroid_lat - lat) ** 2 + (p.centroid_lng - lng) ** 2, default=None)
    if best and ((best.centroid_lat - lat) ** 2 + (best.centroid_lng - lng) ** 2) ** 0.5 < 0.003:
        return best
    return None
