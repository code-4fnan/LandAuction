"""How it works."""

from __future__ import annotations

import streamlit as st

from landauction.config import settings

from . import ui
from .common import PAGES

FEATURES = [
    ("🛰️", "Boundaries you can see",
     "Every listing is traced on satellite imagery, and its area is calculated geodesically "
     "in sq ft, acres and hectares."),
    ("⚡", "Truly live bidding",
     f"Auction rooms refresh every {settings.refresh_seconds} seconds. Rival bids, the price chart "
     "and the countdown all update without a reload."),
    ("🛡️", "Fair by design",
     f"Minimum increments, no self-bidding, and a {settings.anti_snipe_seconds // 60}-minute "
     "anti-snipe window that extends the clock on late bids."),
    ("🔒", "Race-proof bids",
     "Each bid is checked and applied in one database operation. Two people bidding at the same "
     "instant can never both win."),
    ("📈", "Full transparency",
     "Every bid is recorded with bidder and time, and charted, so price discovery happens in the open."),
    ("🧭", "Your dashboard",
     "Track where you're winning, where you've been outbid, what you've won and what you're selling."),
]


def render() -> None:
    ui.section("How LandAuction works", kicker="Guide")
    st.html('<p class="la-prose" style="max-width:760px">Sellers outline a parcel on a satellite map and '
            'open a timed auction. Buyers compete live, and when the clock runs out the highest bid wins.</p>')
    st.html('<div class="la-features">' + "".join(
        f'<div class="la-feature"><div class="la-feature-i">{i}</div><h4>{t}</h4><p>{d}</p></div>'
        for i, t, d in FEATURES) + "</div>")

    ui.section("Auction rules", kicker="The fine print")
    st.markdown(
        f"""
1. **The first bid** must be at least the starting price.
2. **Every later bid** must beat the current price by at least the listing's minimum increment.
3. **You can't bid** on your own listing, or raise your own winning bid.
4. **Anti-sniping:** a bid in the final {settings.anti_snipe_seconds // 60} minutes pushes the end
   time back to {settings.anti_snipe_seconds // 60} minutes after that bid.
5. **When the clock reaches zero,** the highest bidder wins and bidding closes.

> LandAuction is a portfolio project. No real money or property changes hands.
        """
    )
    c1, c2, _ = st.columns([1, 1, 3])
    c1.page_link(PAGES["market"], label="Browse auctions", icon=":material/landscape:")
    c2.page_link(PAGES["sell"], label="List your land", icon=":material/add_location_alt:")
