"""My activity: bids, listings and watchlist for the signed-in user."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from landauction import services
from landauction.db import utcnow

from . import ui
from .common import STATUS_META, db, money, money_compact, open_room, require_login, time_left_label

OUTCOME_LABELS = {"winning": "🟢 Winning", "outbid": "🟠 Outbid", "won": "🏆 Won", "lost": "⚪ Lost"}


def render() -> None:
    user = require_login("see your bids and listings")

    now = utcnow()
    with db() as s:
        bids = services.my_bids(s, user["id"], now=now)
        listings = services.my_listings(s, user["id"])
        watched = services.watched_parcels(s, user["id"])

    winning = sum(a.outcome == "winning" for a in bids)
    outbid = sum(a.outcome == "outbid" for a in bids)
    won = [a for a in bids if a.outcome == "won"]
    st.html(f"""
<div class="la-profile">{ui.avatar(user["username"], 64)}
  <div><div class="la-k" style="color:#E9D7A8">Your dashboard</div>
  <h1>{ui.esc(user["username"])}</h1>
  <div class="la-muted">{len(bids)} auction{"s" if len(bids) != 1 else ""} joined · {len(listings)} listed · {len(watched)} watched</div></div>
</div>""")
    st.html('<div style="height:12px"></div>' + ui.stat_tiles([
        (str(winning), "Currently winning", "you hold the top bid"),
        (str(outbid), "Outbid", "someone bid higher" if outbid else "nothing to chase"),
        (str(len(won)), "Auctions won", money_compact(sum(a.parcel.current_price for a in won)) if won else ""),
        (str(len(listings)), "My listings", f"{sum(p.bid_count for p in listings)} bids received"),
    ]))

    t_bids, t_listings, t_watch = st.tabs([
        f"My bids ({len(bids)})", f"My listings ({len(listings)})", f"Watchlist ({len(watched)})",
    ])

    with t_bids:
        if not bids:
            st.caption("You haven't bid yet. Find a parcel in the Marketplace.")
        else:
            _table("bids", [
                {"id": a.parcel.id, "Parcel": a.parcel.title, "Status": OUTCOME_LABELS[a.outcome],
                 "My best bid": money(a.my_max_bid), "Current price": money(a.parcel.current_price),
                 "My bids": a.my_bid_count, "Ends": time_left_label(a.parcel)}
                for a in bids
            ])

    with t_listings:
        if not listings:
            st.caption("You haven't listed any land yet. Use **Sell land** to start an auction.")
        else:
            _table("listings", [
                {"id": p.id, "Parcel": p.title,
                 "Status": STATUS_META[services.parcel_status(p, now)][0],
                 "Current price": money(p.current_price), "Bids": p.bid_count,
                 "Leader": p.leader.username if p.leader else "–", "Ends": time_left_label(p)}
                for p in listings
            ])

    with t_watch:
        if not watched:
            st.caption("Tap **Watch** in an auction room to keep an eye on it here.")
        else:
            _table("watch", [
                {"id": p.id, "Parcel": p.title,
                 "Status": STATUS_META[services.parcel_status(p, now)][0],
                 "Current price": money(p.current_price), "Bids": p.bid_count, "Ends": time_left_label(p)}
                for p in watched
            ])


def _table(key: str, rows: list[dict]) -> None:
    df = pd.DataFrame(rows)
    event = st.dataframe(
        df, key=f"table_{key}", hide_index=True, on_select="rerun", selection_mode="single-row",
        column_order=[c for c in df.columns if c != "id"],
    )
    st.caption("Select a row to open its auction room.")
    picked = event.selection.rows if event else []
    if picked:
        open_room(int(df.iloc[picked[0]]["id"]))
