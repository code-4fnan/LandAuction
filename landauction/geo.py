"""Small, dependency-free geometry helpers for GeoJSON polygons (lng, lat order)."""

from __future__ import annotations

import math
from typing import Any, Sequence

EARTH_RADIUS_M = 6_378_137.0  # WGS84 equatorial radius, as used by Turf.js
SQM_PER_SQFT = 0.09290304
SQM_PER_ACRE = 4046.8564224
SQM_PER_HECTARE = 10_000.0

MAX_PARCEL_AREA_SQM = 100_000_000  # 100 km²; bigger than this is almost certainly a mistake
MIN_PARCEL_AREA_SQM = 10

Ring = list[list[float]]


class GeometryError(ValueError):
    pass


def outer_ring(geometry: dict[str, Any]) -> Ring:
    """Return the closed outer ring of a GeoJSON Polygon, validating it."""
    if not isinstance(geometry, dict) or geometry.get("type") != "Polygon":
        raise GeometryError("Boundary must be a polygon.")
    coords = geometry.get("coordinates") or []
    if not coords or not isinstance(coords[0], list):
        raise GeometryError("Polygon has no coordinates.")
    ring = [[float(p[0]), float(p[1])] for p in coords[0]]
    for lng, lat in ring:
        if not (-180 <= lng <= 180 and -90 <= lat <= 90):
            raise GeometryError("Polygon has coordinates outside the valid range.")
    if ring and ring[0] != ring[-1]:
        ring.append(list(ring[0]))
    if len({tuple(p) for p in ring}) < 3:
        raise GeometryError("A boundary needs at least 3 distinct corners.")
    return ring


def ring_area_sqm(ring: Sequence[Sequence[float]]) -> float:
    """Geodesic area of a closed ring in m² (spherical-excess method from geojson-area)."""
    n = len(ring)
    if n < 3:
        return 0.0
    total = 0.0
    for i in range(n):
        if i == n - 2:
            lo, mid, up = n - 2, n - 1, 0
        elif i == n - 1:
            lo, mid, up = n - 1, 0, 1
        else:
            lo, mid, up = i, i + 1, i + 2
        total += (math.radians(ring[up][0]) - math.radians(ring[lo][0])) * math.sin(
            math.radians(ring[mid][1])
        )
    return abs(total * EARTH_RADIUS_M**2 / 2.0)


def ring_centroid(ring: Sequence[Sequence[float]]) -> tuple[float, float]:
    """Vertex-average centre as (lat, lng); accurate enough for parcel-sized shapes."""
    pts = list(ring[:-1]) if len(ring) > 1 and list(ring[0]) == list(ring[-1]) else list(ring)
    lng = sum(p[0] for p in pts) / len(pts)
    lat = sum(p[1] for p in pts) / len(pts)
    return lat, lng


def point_in_ring(lng: float, lat: float, ring: Sequence[Sequence[float]]) -> bool:
    """Ray-casting point-in-polygon test."""
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        if (yi > lat) != (yj > lat) and lng < (xj - xi) * (lat - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def bounds(rings: Sequence[Sequence[Sequence[float]]]) -> list[list[float]]:
    """[[south, west], [north, east]] covering all rings (Leaflet order)."""
    lats = [p[1] for r in rings for p in r]
    lngs = [p[0] for r in rings for p in r]
    return [[min(lats), min(lngs)], [max(lats), max(lngs)]]


def latlngs(ring: Sequence[Sequence[float]]) -> list[list[float]]:
    """Convert a GeoJSON ring (lng, lat) to Leaflet/folium order (lat, lng)."""
    return [[p[1], p[0]] for p in ring]


def format_area(sqm: float) -> str:
    if sqm >= SQM_PER_ACRE:
        return f"{sqm / SQM_PER_ACRE:,.2f} acres ({sqm / SQM_PER_HECTARE:,.2f} ha)"
    return f"{sqm / SQM_PER_SQFT:,.0f} sq ft ({sqm:,.0f} m²)"
