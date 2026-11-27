"""LandAuction: real-time land auctions on a map.

Run locally:   streamlit run streamlit_app.py
Deploy:        push to GitHub, then create an app on share.streamlit.io with this file.
"""

from __future__ import annotations

import streamlit as st

from app_pages import about, activity, marketplace, room, sell, ui
from app_pages.common import PAGES, current_user, db, flash, init_database, show_flashes, sign_in, sign_out
from landauction import services
from landauction.config import settings
from landauction.seed import DEMO_PASSWORD

st.set_page_config(page_title="LandAuction · Live land auctions", page_icon=str(ui.ASSETS / "logo_mark.svg"),
                   layout="wide", initial_sidebar_state="collapsed")

init_database()
ui.inject_css()
st.logo(str(ui.ASSETS / "logo.svg"), size="large")

PAGES.update({
    "market": st.Page(marketplace.render, title="Marketplace", icon=":material/landscape:",
                      url_path="marketplace", default=True),
    "room": st.Page(room.render, title="Auction room", icon=":material/gavel:", url_path="auction",
                    visibility="hidden"),
    "sell": st.Page(sell.render, title="Sell land", icon=":material/add_location_alt:", url_path="sell"),
    "activity": st.Page(activity.render, title="My activity", icon=":material/dashboard:", url_path="activity"),
    "about": st.Page(about.render, title="How it works", icon=":material/menu_book:", url_path="about"),
})


def account_bar() -> None:
    """Top-right account menu, shown above every page."""
    left, right = st.columns([5, 1.25], vertical_alignment="center")
    left.html('<div class="la-brandline">Live, transparent land auctions across India · '
              'Verified boundaries on satellite imagery</div>')
    user = current_user()
    with right:
        if user:
            with st.popover(user["username"], icon=":material/account_circle:", width="stretch"):
                st.html(f'<div style="display:flex;gap:10px;align-items:center">{ui.avatar(user["username"], 40)}'
                        f'<div><div class="la-v">{ui.esc(user["username"])}</div>'
                        f'<div class="la-note">Signed in</div></div></div>')
                if st.button("My activity", icon=":material/dashboard:", width="stretch"):
                    st.switch_page(PAGES["activity"])
                if st.button("List land for auction", icon=":material/add_location_alt:", width="stretch"):
                    st.switch_page(PAGES["sell"])
                if st.button("Log out", icon=":material/logout:", width="stretch"):
                    sign_out()
                    st.rerun()
            return
        with st.popover("Sign in", icon=":material/login:", width="stretch"):
            _auth_forms()


def _auth_forms() -> None:
    login_tab, register_tab = st.tabs(["Log in", "Create account"])
    with login_tab:
        with st.form("login", border=False):
            username = st.text_input("Username", autocomplete="username")
            password = st.text_input("Password", type="password", autocomplete="current-password")
            if st.form_submit_button("Log in", type="primary", width="stretch"):
                with db() as s:
                    found = services.authenticate(s, username, password)
                if found:
                    sign_in(found)
                    flash("success", f"Welcome back, {found.username}!")
                    st.rerun()
                st.error("Wrong username or password.")
    with register_tab:
        with st.form("register", border=False):
            username = st.text_input("Username", key="reg_user", help="3–30 letters, numbers or _")
            email = st.text_input("Email", key="reg_email", autocomplete="email")
            password = st.text_input("Password", type="password", key="reg_pw",
                                     help="At least 8 characters", autocomplete="new-password")
            if st.form_submit_button("Create account", type="primary", width="stretch"):
                try:
                    with db() as s:
                        new_user = services.register_user(s, username, email, password)
                except services.ValidationError as exc:
                    st.error(str(exc))
                else:
                    sign_in(new_user)
                    flash("success", f"Account created. Welcome, {new_user.username}!")
                    st.rerun()

    if settings.seed_demo_data:
        st.divider()
        if st.button("Explore with the demo account", icon=":material/play_circle:", width="stretch"):
            with db() as s:
                demo = services.authenticate(s, "demo", DEMO_PASSWORD)
            if demo:
                sign_in(demo)
                flash("success", "Signed in as the demo user. Happy bidding!")
                st.rerun()
            st.error("The demo account isn't available.")


page = st.navigation(list(PAGES.values()), position="top")
account_bar()
if page.url_path != "auction":
    show_flashes()  # the auction room shows them inside its live panel
page.run()

st.html(
    '<div class="la-footer"><div><b>LandAuction</b> &nbsp;·&nbsp; A portfolio project. '
    "No real money or property changes hands.</div>"
    "<div>Imagery © Esri, Maxar, Earthstar Geographics · Maps © OpenStreetMap contributors</div></div>"
)
