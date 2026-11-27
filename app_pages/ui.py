"""Visual building blocks: satellite imagery, cards, pills, stat tiles, countdown.

Everything here returns or renders HTML styled by ``assets/style.css``. Any text
that came from users goes through ``esc`` before it reaches the page.
"""

from __future__ import annotations

import base64
import html
import math
from pathlib import Path
from typing import Iterable, Sequence

import streamlit as st

from landauction import geo, services
from landauction.db import Parcel

ASSETS = Path(__file__).resolve().parent.parent / "assets"
TILE = 256
ESRI_TILE = "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
OSM_TILE = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"

STATUS_LABELS = {"live": "Live", "ending_soon": "Ending soon", "ended": "Closed"}


def esc(text: str | None) -> str:
    return html.escape(text or "", quote=True)


def inject_css() -> None:
    st.html(f"<style>{(ASSETS / 'style.css').read_text(encoding='utf-8')}</style>")


# ----------------------------------------------------------------------------- satellite


def _px(lng: float, lat: float, z: int) -> tuple[float, float]:
    """Web-Mercator world pixel coordinates at zoom z."""
    n = TILE * 2**z
    lat = max(min(lat, 85.05), -85.05)
    s = math.sin(math.radians(lat))
    return (lng + 180.0) / 360.0 * n, (0.5 - math.log((1 + s) / (1 - s)) / (4 * math.pi)) * n


def satellite(
    rings: Sequence[geo.Ring] = (),
    *,
    width: int = 640,
    height: int = 400,
    center: tuple[float, float] | None = None,  # (lat, lng)
    zoom: int | None = None,
    fill: float = 0.5,
    max_zoom: int = 18,
    dots: Iterable[tuple[float, float]] = (),  # (lat, lng) glowing markers
    outline: bool = True,
    tiles: str = "esri",  # or "osm" for a street map
) -> str:
    """Satellite image of an area, stitched from map tiles, with parcel outlines on top.

    Returns a div whose children are absolutely positioned in percentages, so it
    scales to whatever box it's put in (the box should have the same aspect ratio).
    """
    pts = [p for r in rings for p in r]
    if zoom is None:
        zoom = max_zoom
        if pts:
            while zoom > 2:
                xs, ys = zip(*(_px(p[0], p[1], zoom) for p in pts))
                if max(xs) - min(xs) <= width * fill and max(ys) - min(ys) <= height * fill:
                    break
                zoom -= 1
    if center is None and pts:
        xs, ys = zip(*(_px(p[0], p[1], zoom) for p in pts))
        cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
    else:
        lat, lng = center or (12.9716, 77.5946)
        cx, cy = _px(lng, lat, zoom)
    left, top = cx - width / 2, cy - height / 2
    n_tiles = 2**zoom

    imgs = []
    for tx in range(math.floor(left / TILE), math.floor((left + width) / TILE) + 1):
        for ty in range(math.floor(top / TILE), math.floor((top + height) / TILE) + 1):
            if not 0 <= ty < n_tiles:
                continue
            url = (OSM_TILE if tiles == "osm" else ESRI_TILE).format(z=zoom, y=ty, x=tx % n_tiles)
            x, y = tx * TILE - left, ty * TILE - top
            # +0.4% overlap hides hairline seams between tiles when scaled.
            imgs.append(
                f'<img src="{url}" alt="" loading="lazy" style="left:{x / width * 100:.3f}%;'
                f"top:{y / height * 100:.3f}%;width:{TILE / width * 100 + 0.4:.3f}%;"
                f'height:{TILE / height * 100 + 0.4:.3f}%">'
            )

    # st.html strips inline <svg>, so the overlay is an SVG image (data URI) with inline styles.
    shapes = []
    for ring in rings if outline else ():
        coords = " ".join(
            f"{x - left:.1f},{y - top:.1f}" for x, y in (_px(p[0], p[1], zoom) for p in ring)
        )
        shapes.append(
            f'<polygon points="{coords}" fill="none" stroke="rgba(0,0,0,0.45)" stroke-width="7" stroke-linejoin="round"/>'
            f'<polygon points="{coords}" fill="rgba(255,209,102,0.18)" stroke="#FFD166" stroke-width="3" stroke-linejoin="round"/>'
        )
    for lat, lng in dots:
        x, y = _px(lng, lat, zoom)
        cx, cy = f"{x - left:.1f}", f"{y - top:.1f}"
        shapes.append(
            f'<circle cx="{cx}" cy="{cy}" r="14" fill="rgba(255,209,102,0.35)">'
            '<animate attributeName="r" values="10;30;10" dur="2.4s" repeatCount="indefinite"/>'
            '<animate attributeName="opacity" values="1;0.15;1" dur="2.4s" repeatCount="indefinite"/></circle>'
            f'<circle cx="{cx}" cy="{cy}" r="8" fill="#FFD166" stroke="#fff" stroke-width="2.5"/>'
        )
    overlay = ""
    if shapes:
        svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" '
               f'preserveAspectRatio="none">{"".join(shapes)}</svg>')
        uri = "data:image/svg+xml;base64," + base64.b64encode(svg.encode("utf-8")).decode("ascii")
        overlay = f'<img class="la-overlay" src="{uri}" alt="">'
    return f'<div class="la-sat">{"".join(imgs)}{overlay}</div>'


# ----------------------------------------------------------------------------- small pieces


def pill(status: str, extra_class: str = "") -> str:
    return (f'<span class="la-pill la-{status} {extra_class}"><span class="la-dot"></span>'
            f"{STATUS_LABELS[status]}</span>")


def stat_tiles(items: Sequence[tuple[str, str, str]], dark: bool = False) -> str:
    """[(value, label, sublabel)] -> a row of stat tiles."""
    cells = "".join(
        f'<div class="la-stat"><div class="la-stat-v">{v}</div><div class="la-stat-k">{esc(k)}</div>'
        + (f'<div class="la-stat-s">{esc(s)}</div>' if s else "")
        + "</div>"
        for v, k, s in items
    )
    return f'<div class="la-stats {"la-stats-dark" if dark else ""}">{cells}</div>'


def section(title: str, kicker: str = "", aside: str = "") -> None:
    st.html(
        '<div class="la-section"><div>'
        + (f'<div class="la-kicker">{esc(kicker)}</div>' if kicker else "")
        + f'<h2 class="la-h2">{esc(title)}</h2></div>'
        + (f'<div class="la-section-aside">{aside}</div>' if aside else "")
        + "</div>"
    )


def facts(items: Sequence[tuple[str, str]]) -> str:
    cells = "".join(f'<div class="la-fact"><div class="la-k">{esc(k)}</div>'
                    f'<div class="la-fact-v">{esc(v)}</div></div>' for k, v in items)
    return f'<div class="la-facts">{cells}</div>'


def avatar(name: str, size: int = 36) -> str:
    palette = ["#1E5B3C", "#8A5A2B", "#3D5A80", "#6B4E71", "#B5652B", "#2F6F6F"]
    color = palette[sum(map(ord, name)) % len(palette)]
    return (f'<span class="la-avatar" style="width:{size}px;height:{size}px;background:{color};'
            f'font-size:{size * 0.42:.0f}px">{esc(name[:1].upper())}</span>')


# ----------------------------------------------------------------------------- cards


def parcel_card_html(p: Parcel, *, price: str, time_left: str, photos: int = 0) -> str:
    status = services.parcel_status(p)
    ring = services.parcel_ring(p)
    area = geo.format_area(p.area_sqm).split(" (")[0]
    bids = f"{p.bid_count} bid{'s' if p.bid_count != 1 else ''}"
    views = (f"{photos} photo{'s' if photos != 1 else ''} + " if photos else "") + "6 views"
    return f"""
<div class="la-thumb">
  {satellite([ring], width=640, height=400, fill=0.45, max_zoom=19)}
  {pill(status)}
  <span class="la-chip la-chip-tr">📷 {views}</span>
  <span class="la-chip la-chip-br">{esc(area)}</span>
  <span class="la-chip la-chip-bl">⏱ {esc(time_left)}</span>
</div>
<div class="la-card-body">
  <div class="la-loc">{esc(p.location) or "Location not given"}</div>
  <div class="la-card-title" title="{esc(p.title)}">{esc(p.title)}</div>
  <div class="la-card-row">
    <div><div class="la-k">{"Current bid" if p.bid_count else "Starting at"}</div>
         <div class="la-price">{price}</div></div>
    <div class="la-right"><div class="la-k">Activity</div><div class="la-v">{bids}</div></div>
  </div>
</div>"""


# ----------------------------------------------------------------------------- countdown


def countdown(end_epoch_ms: int, *, height: int = 74) -> None:
    """A ticking d/h/m/s countdown. The HTML only changes when the end time does,
    so the iframe keeps running smoothly across fragment reruns."""
    # Only server-computed numbers go in this HTML, so an iframe with scripts is safe here.
    st.iframe(
        f"""
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@500;700&display=swap" rel="stylesheet">
<style>
  body {{ margin:0; font-family:Inter, system-ui, sans-serif; background:transparent; }}
  .row {{ display:flex; gap:8px; }}
  .cell {{ flex:1; background:#F4F0E6; border:1px solid #E3DCCB; border-radius:12px;
           padding:10px 0 8px; text-align:center; transition:background .3s, color .3s; }}
  .n {{ font-size:26px; font-weight:700; color:#14201A; font-variant-numeric:tabular-nums; line-height:1; }}
  .l {{ font-size:10px; letter-spacing:.12em; text-transform:uppercase; color:#6B7368; margin-top:6px; }}
  .urgent .cell {{ background:#FDEBE3; border-color:#F4C7B3; }}
  .urgent .n {{ color:#B4441C; }}
  .done {{ text-align:center; padding:22px 0; border-radius:12px; background:#EEE; color:#555;
           font-weight:700; letter-spacing:.08em; text-transform:uppercase; font-size:13px; }}
</style>
<div id="root" class="row">
  <div class="cell"><div class="n" id="d">--</div><div class="l">Days</div></div>
  <div class="cell"><div class="n" id="h">--</div><div class="l">Hours</div></div>
  <div class="cell"><div class="n" id="m">--</div><div class="l">Min</div></div>
  <div class="cell"><div class="n" id="s">--</div><div class="l">Sec</div></div>
</div>
<script>
  const end = {int(end_epoch_ms)};
  const pad = n => String(n).padStart(2, "0");
  function tick() {{
    const left = end - Date.now(), root = document.getElementById("root");
    if (left <= 0) {{ root.outerHTML = '<div class="done">Bidding closed</div>'; clearInterval(t); return; }}
    const s = Math.floor(left / 1000);
    document.getElementById("d").textContent = pad(Math.floor(s / 86400));
    document.getElementById("h").textContent = pad(Math.floor(s % 86400 / 3600));
    document.getElementById("m").textContent = pad(Math.floor(s % 3600 / 60));
    document.getElementById("s").textContent = pad(s % 60);
    root.classList.toggle("urgent", left < 3600 * 1000);
  }}
  const t = setInterval(tick, 1000); tick();
</script>""",
        height=height,
    )


# ----------------------------------------------------------------------------- gallery

GALLERY_W, GALLERY_H = 1400, 560


def _data_uri(jpeg: bytes) -> str:
    return "data:image/jpeg;base64," + base64.b64encode(jpeg).decode("ascii")


def aerial_views(p: Parcel) -> list[tuple[str, str]]:
    """Generated views of the plot from different heights and angles: (label, html)."""
    ring = services.parcel_ring(p)
    flat = lambda **kw: satellite([ring], width=GALLERY_W, height=GALLERY_H, **kw)  # noqa: E731
    # Tilted views render a square of imagery that CSS lays back in 3D perspective.
    tilted = lambda cls: (  # noqa: E731
        f'<div class="la-tilt {cls}">{satellite([ring], width=1400, height=1400, fill=0.22, max_zoom=19)}'
        '<div class="la-sky"></div></div>'
    )
    return [
        ("Aerial · close-up", flat(fill=0.55, max_zoom=19)),
        ("Bird's-eye · from the south", tilted("la-tilt-s")),
        ("Bird's-eye · from the north-east", tilted("la-tilt-ne")),
        ("Neighbourhood", flat(fill=0.12, max_zoom=19)),
        ("Area context", flat(fill=0.02, max_zoom=19, dots=[(p.centroid_lat, p.centroid_lng)])),
        ("Street map", flat(fill=0.3, max_zoom=18, tiles="osm")),
    ]


def gallery(p: Parcel, photos: Sequence, *, key: str, overlay: str = "") -> str:
    """A click-through gallery: seller photos first, then generated aerial views.

    Built from radio buttons + CSS (no JavaScript), so switching slides is instant
    and doesn't rerun the app. ``overlay`` is HTML laid over every slide.
    """
    slides: list[tuple[str, str, str]] = []  # (label, stage html, thumb html)
    for i, ph in enumerate(photos, 1):
        label = ph.caption or f"Seller photo {i}"
        stage = f'<img class="la-photo" src="{_data_uri(ph.data)}" alt="{esc(label)}">'
        thumb = f'<img class="la-photo-thumb" src="{_data_uri(ph.thumb)}" alt="">'
        slides.append((label, stage, thumb))
    for label, html_ in aerial_views(p):
        slides.append((label, html_, html_))  # same tiles, so thumbnails come from the browser cache

    gid = f"g-{key}"
    n = len(slides)
    radios = "".join(
        f'<input type="radio" class="la-g-radio" name="{gid}" id="{gid}-{i}"{" checked" if i == 0 else ""}>'
        for i in range(n)
    )
    stage = "".join(
        f'<figure class="la-slide la-s{i}">{body}'
        f'<figcaption><span class="la-g-count">{i + 1} / {n}</span>{esc(label)}</figcaption></figure>'
        for i, (label, body, _) in enumerate(slides)
    )
    thumbs = "".join(
        f'<label for="{gid}-{i}" class="la-thumb-btn la-t{i}" title="{esc(label)}">'
        f'<span class="la-thumb-img">{thumb}</span><span class="la-thumb-l">{esc(label)}</span></label>'
        for i, (label, _, thumb) in enumerate(slides)
    )
    rules = "".join(
        f"#{gid}-{i}:checked ~ .la-stage .la-s{i}{{display:block}}"
        f"#{gid}-{i}:checked ~ .la-thumbs .la-t{i}{{border-color:var(--gold);opacity:1}}"
        for i in range(n)
    )
    return (f"<style>{rules}</style><div class=\"la-gallery\">{radios}"
            f'<div class="la-stage">{stage}{overlay}</div><div class="la-thumbs">{thumbs}</div></div>')
