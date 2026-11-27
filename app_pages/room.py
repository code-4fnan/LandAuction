"""Auction room: satellite hero, parcel facts, and a live bidding panel."""

from __future__ import annotations

from datetime import timezone

import folium
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from streamlit_folium import st_folium

from landauction import fmt, geo, services
from landauction.config import settings
from landauction.db import utcnow

from . import ui
from .common import (
    PAGES, add_parcels, base_map, current_user, db, flash, local_time, money, money_compact,
    save_photos, show_flashes,
)


def render() -> None:
    parcel_id = _resolve_parcel_id()
    if parcel_id is None:
        return

    with db() as s:
        parcel = services.get_parcel(s, parcel_id)
        user = current_user()
        watching = bool(user) and services.is_watching(s, user["id"], parcel_id)
        photos = services.list_photos(s, parcel_id)
    if parcel is None:
        st.error("That auction doesn't exist.")
        st.page_link(PAGES["market"], label="Back to the marketplace", icon=":material/arrow_back:")
        return

    st.session_state["parcel_id"] = parcel_id
    st.query_params["parcel"] = str(parcel_id)

    nav_l, nav_r = st.columns([4, 1.2], vertical_alignment="center")
    with nav_l:
        st.page_link(PAGES["market"], label="All auctions", icon=":material/arrow_back:")
    with nav_r:
        if user and user["id"] != parcel.seller_id:
            if st.button("Watching" if watching else "Add to watchlist",
                         icon=":material/bookmark_added:" if watching else ":material/bookmark_add:",
                         width="stretch"):
                with db() as s:
                    now_watching = services.toggle_watch(s, user["id"], parcel_id)
                flash("info", "Added to your watchlist." if now_watching else "Removed from your watchlist.")
                st.rerun()

    _hero(parcel, photos)

    left, right = st.columns([1.55, 1], gap="large")
    with left:
        _details(parcel)
        if user and user["id"] == parcel.seller_id:
            _manage_photos(parcel, photos, user["id"])
    with right:
        with st.container(key="bidpanel"):
            live_panel(parcel_id)
            _bid_form(parcel_id)

    _history_section(parcel_id)


def _resolve_parcel_id() -> int | None:
    raw = st.query_params.get("parcel") or st.session_state.get("parcel_id")
    try:
        if raw is not None:
            return int(raw)
    except (TypeError, ValueError):
        pass

    ui.section("Choose an auction", kicker="Auction room")
    with db() as s:
        parcels = services.list_parcels(s, status="active")
    if not parcels:
        st.info("There are no live auctions right now.")
        return None
    choice = st.selectbox("Choose an auction", parcels, index=None, placeholder="Select a parcel…",
                          format_func=lambda p: f"{p.title} · {money(p.current_price)}",
                          label_visibility="collapsed")
    if choice:
        st.session_state["parcel_id"] = choice.id
        st.rerun()
    return None


def _hero(p, photos) -> None:
    status = services.parcel_status(p)
    overlay = f"""
<div class="la-stage-overlay"><div class="la-room-hero-content">
  {ui.pill(status)}
  <h1>{ui.esc(p.title)}</h1>
  <div class="la-sub">{ui.esc(p.location) or "Location not given"} &nbsp;·&nbsp; Listed by
    <b>{ui.esc(p.seller.username)}</b> &nbsp;·&nbsp; Lot #{p.id:04d}</div>
</div></div>"""
    st.html(ui.gallery(p, photos, key=f"room{p.id}", overlay=overlay))


def _manage_photos(p, photos, user_id: int) -> None:
    with st.expander(f"Manage your photos ({len(photos)}/{services.MAX_PHOTOS})", icon=":material/photo_library:"):
        if photos:
            cols = st.columns(4)
            for i, ph in enumerate(photos):
                with cols[i % 4]:
                    st.image(ph.thumb, caption=ph.caption or f"Photo {i + 1}")
                    if st.button("Remove", key=f"rm_photo_{ph.id}", icon=":material/delete:", width="stretch"):
                        with db() as s:
                            services.delete_photo(s, photo_id=ph.id, user_id=user_id)
                        flash("info", "Photo removed.")
                        st.rerun()
        if len(photos) >= services.MAX_PHOTOS:
            st.caption("You've reached the photo limit. Remove one to add another.")
            return
        with st.form(f"add_photos_{p.id}", clear_on_submit=True, border=False):
            files = st.file_uploader("Add photos of the land, access road, boundary stones, views…",
                                     type=["jpg", "jpeg", "png", "webp"], accept_multiple_files=True)
            caption = st.text_input("Caption (optional)", max_chars=120, placeholder="e.g. View from the access road")
            if st.form_submit_button("Upload photos", type="primary", icon=":material/upload:"):
                room = services.MAX_PHOTOS - len(photos)
                saved, errors = save_photos(p.id, user_id, (files or [])[:room], caption)
                for err in errors:
                    flash("error", err)
                if saved:
                    flash("success", f"Added {saved} photo{'s' if saved != 1 else ''}.")
                st.rerun()


def _details(p) -> None:
    sqft = p.area_sqm / geo.SQM_PER_SQFT
    area_main, _, area_alt = geo.format_area(p.area_sqm).partition(" (")
    ui.section("Parcel overview", kicker="The land")
    st.html(ui.facts([
        ("Land area", area_main),
        ("Also", area_alt.rstrip(")") or "–"),
        ("Price / sq ft", money(p.current_price / sqft) if sqft else "–"),
        ("Starting price", money(p.starting_price)),
        ("Bid increment", money(p.min_increment)),
        ("Listed", fmt.to_local(p.created_at, settings.timezone).strftime("%d %b %Y")),
    ]))
    st.html(f'<p class="la-prose" style="margin-top:1rem">{ui.esc(p.description) or "The seller has not added a description."}</p>')

    with st.expander("Explore the boundary on an interactive map", icon=":material/map:"):
        m = base_map(satellite=True)
        rings = add_parcels(m, [p], highlight_id=p.id)
        m.fit_bounds(geo.bounds(rings), padding=(40, 40), max_zoom=18)
        folium.LayerControl(collapsed=True).add_to(m)
        st_folium(m, key=f"room_map_{p.id}", height=420, use_container_width=True, returned_objects=[])
        st.caption(f"Centre {p.centroid_lat:.5f}, {p.centroid_lng:.5f}")


@st.fragment(run_every=settings.refresh_seconds)
def live_panel(parcel_id: int) -> None:
    """Re-runs on its own every few seconds, so other people's bids show up without a reload."""
    if st.session_state.pop("_room_full_rerun", False):
        st.rerun()  # a quick bid changed things outside this fragment (e.g. the custom-bid form)
    show_flashes()
    with db() as s:
        p = services.get_parcel(s, parcel_id)
    if p is None:
        st.error("This auction was removed.")
        return
    user = current_user()
    _notify_new_bids(p, user)

    status = services.parcel_status(p, utcnow())
    is_me = bool(user and p.leader_id == user["id"])
    label = ("Winning bid" if status == "ended" else "Current bid") if p.bid_count else "Starting price"
    count = f"{p.bid_count} bid{'s' if p.bid_count != 1 else ''}"

    if p.leader:
        who = "You" if is_me else ui.esc(p.leader.username)
        verb = ("won this auction" if status == "ended" else "are winning") if is_me else (
            "won this auction" if status == "ended" else "is the highest bidder")
        leader = (f'<div class="la-leader {"me" if is_me else ""}">{ui.avatar(p.leader.username)}'
                  f'<div><div class="la-v">{who} {verb}</div><div class="la-note">{count} so far</div></div></div>')
    else:
        leader = '<div class="la-leader"><div><div class="la-v">No bids yet</div><div class="la-note">Be the first to bid</div></div></div>'

    st.html(f"""
<div class="la-bid-top"><span class="la-k">{label}</span>{ui.pill(status)}</div>
<div class="la-price-xl">{money(p.current_price)}</div>
<div class="la-price-sub">{money_compact(p.current_price)} &nbsp;·&nbsp; {count}</div>
{leader}""")

    if status == "ended":
        st.html(f'<div class="la-closed"><div class="la-k">Auction closed</div>'
                f'<div class="la-v">{local_time(p.end_time)}</div></div>')
        return

    st.html('<div class="la-k" style="margin-top:14px">Time remaining</div>')
    ui.countdown(int(p.end_time.replace(tzinfo=timezone.utc).timestamp() * 1000))
    st.html(f'<div class="la-next"><span class="la-k">Minimum next bid</span>'
            f'<span class="la-v">{money(services.minimum_next_bid(p))}</span></div>'
            f'<div class="la-note">Closes {local_time(p.end_time)}. A bid in the final '
            f'{settings.anti_snipe_seconds // 60} minutes extends the clock.</div>')

    if not user:
        st.info("Sign in (top right) to place a bid.", icon=":material/lock:")
    elif user["id"] == p.seller_id:
        st.info("This is your listing, so you can't bid on it.", icon=":material/storefront:")
    elif not is_me:
        st.html('<div class="la-k" style="margin-top:10px">Quick bid</div>')
        cols = st.columns(3)
        base = services.minimum_next_bid(p)
        for col, steps in zip(cols, (0, 2, 5)):
            amount = base + steps * p.min_increment
            col.button(money_compact(amount), key=f"quick_{steps}", width="stretch",
                       type="primary" if steps == 0 else "secondary", help=f"Bid {money(amount)}",
                       on_click=_place_bid, args=(parcel_id, amount))


def _notify_new_bids(p, user) -> None:
    """Toast when the bid count goes up while this room is open."""
    seen = st.session_state.setdefault("seen_bids", {})
    previous = seen.get(p.id)
    seen[p.id] = p.bid_count
    if previous is None or p.bid_count <= previous or not p.leader:
        return
    if user and p.leader_id == user["id"]:
        return  # our own bid; _place_bid already confirmed it
    st.toast(f"New bid: {money(p.current_price)} by {p.leader.username}", icon=":material/campaign:")


def _place_bid(parcel_id: int, amount: int) -> None:
    user = current_user()
    if not user:
        flash("error", "Sign in to place a bid.")
        return
    try:
        with db() as s:
            result = services.place_bid(s, parcel_id=parcel_id, bidder_id=user["id"], amount=amount,
                                        anti_snipe_seconds=settings.anti_snipe_seconds)
    except services.BidRejected as exc:
        flash("error", str(exc))
        return
    msg = f"Bid of {money(result.amount)} placed. You're the highest bidder."
    if result.extended:
        msg += " The auction was extended."
    flash("success", msg)
    st.session_state["_room_full_rerun"] = True


def _bid_form(parcel_id: int) -> None:
    with db() as s:
        p = services.get_parcel(s, parcel_id)
    user = current_user()
    if (not p or not user or user["id"] in (p.seller_id, p.leader_id)
            or services.parcel_status(p) == "ended"):
        return
    minimum = services.minimum_next_bid(p)
    with st.form("custom_bid", clear_on_submit=True, border=False):
        a, b = st.columns([1.6, 1], vertical_alignment="bottom")
        amount = a.number_input(f"Or enter your own bid ({settings.currency_symbol})", value=minimum,
                                step=p.min_increment, format="%d", help=f"At least {money(minimum)} right now")
        if b.form_submit_button("Place bid", type="primary", icon=":material/gavel:", width="stretch"):
            _place_bid(parcel_id, int(amount))
            st.session_state.pop("_room_full_rerun", None)  # this rerun already covers it
            st.rerun()


@st.fragment(run_every=settings.refresh_seconds * 2)
def _history_section(parcel_id: int) -> None:
    with db() as s:
        p = services.get_parcel(s, parcel_id)
        bids = services.bid_history(s, parcel_id)
    if p is None:
        return
    ui.section("Bidding activity", kicker="Live feed",
               aside=f"{len(bids)} bid{'s' if len(bids) != 1 else ''} · updates automatically")
    if not bids:
        st.caption("No bids yet. The first bid sets the pace.")
        return

    chart_col, feed_col = st.columns([1.55, 1], gap="large")
    with chart_col:
        local = lambda dt: fmt.to_local(dt, settings.timezone).replace(tzinfo=None)  # noqa: E731
        df = pd.DataFrame(
            [{"Time": local(p.created_at), "Amount": p.starting_price, "Bidder": "Starting price"}]
            + [{"Time": local(b.created_at), "Amount": b.amount, "Bidder": b.bidder.username}
               for b in reversed(bids)]
        )
        fig = go.Figure(go.Scatter(
            x=df["Time"], y=df["Amount"], mode="lines+markers", line_shape="hv",
            line=dict(color="#1E5B3C", width=3), fill="tozeroy", fillcolor="rgba(30,91,60,0.08)",
            marker=dict(size=8, color="#C9973B", line=dict(color="#fff", width=2)),
            hovertext=[f"<b>{ui.esc(b)}</b><br>{money(a)}" for b, a in zip(df["Bidder"], df["Amount"])],
            hovertemplate="%{hovertext}<br>%{x|%d %b, %H:%M}<extra></extra>",
        ))
        # Plot in crore / lakh so the axis reads like Indian property prices.
        unit, div = (" Cr", 1e7) if df["Amount"].max() >= 1e7 else (" L", 1e5) if df["Amount"].max() >= 1e5 else ("", 1)
        if settings.currency_symbol != "₹":
            unit, div = "", 1
        fig.update_traces(y=df["Amount"] / div)
        lo, hi = df["Amount"].min() / div, df["Amount"].max() / div
        pad = (hi - lo) * 0.2 or hi * 0.05
        fig.update_layout(
            height=330, margin=dict(l=0, r=0, t=10, b=0), showlegend=False,
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
            font=dict(family="Inter, sans-serif", color="#46504a"),
            yaxis=dict(range=[lo - pad, hi + pad], gridcolor="#E3DCCB",
                       tickprefix=settings.currency_symbol, ticksuffix=unit,
                       tickformat=".2f" if div > 1 else ",.0f", zeroline=False),
            xaxis=dict(showgrid=False),
            hoverlabel=dict(bgcolor="#14201A", font_color="#fff"),
        )
        st.plotly_chart(fig, key=f"history_chart_{parcel_id}", config={"displayModeBar": False})
    with feed_col:
        rows = []
        for i, b in enumerate(bids[:7]):
            rows.append(
                f'<div class="la-tl-row {"top" if i == 0 else ""}">{ui.avatar(b.bidder.username, 32)}'
                f'<div class="la-tl-main"><div class="la-tl-name">{ui.esc(b.bidder.username)}'
                f'{" · leading" if i == 0 and services.parcel_status(p) != "ended" else ""}</div>'
                f'<div class="la-tl-time">{local_time(b.created_at)}</div></div>'
                f'<div class="la-tl-amt">{money(b.amount)}</div></div>'
            )
        more = f'<div class="la-note" style="padding:6px 12px">+ {len(bids) - 7} earlier bids</div>' if len(bids) > 7 else ""
        st.html(f'<div class="la-timeline">{"".join(rows)}{more}</div>')
