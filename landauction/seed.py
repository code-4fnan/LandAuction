"""Demo data so a fresh deployment isn't an empty map.

Runs only when the database has no parcels. Demo accounts all use the
password ``demo1234``.
"""

from __future__ import annotations

import math
import random
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import services
from .db import Parcel, User, utcnow

DEMO_PASSWORD = "demo1234"
DEMO_USERS = ["demo", "priya_estates", "rahul_k", "greenacres", "meera_s"]

# (title, location, description, lat, lng, half-size in degrees, start price, increment, hours left)
DEMO_PARCELS = [
    ("Lakeview Residential Plot", "Hebbal, Bengaluru",
     "Corner plot near Hebbal Lake with a clear title, 40 ft road access and BBMP approval.",
     13.0450, 77.5970, 0.00012, 30_000_000, 200_000, 30),
    ("Whitefield Tech Corridor Land", "Whitefield, Bengaluru",
     "Commercial-zoned land 1 km from ITPL. Suitable for office or mixed-use development.",
     12.9698, 77.7500, 0.0006, 450_000_000, 5_000_000, 72),
    ("Nandi Hills Farmland", "Nandi Hills Road, Chikkaballapur",
     "Fertile agricultural land with a borewell, mango trees and views of Nandi Hills.",
     13.3702, 77.6835, 0.0012, 60_000_000, 500_000, 0.75),
    ("Electronic City Industrial Plot", "Electronic City Phase 2, Bengaluru",
     "KIADB industrial plot with power and water connections in place.",
     12.8399, 77.6770, 0.0005, 120_000_000, 1_000_000, 120),
    ("Sarjapur Villa Plot", "Sarjapur Road, Bengaluru",
     "Gated-layout villa plot near schools and the upcoming metro line.",
     12.9100, 77.6870, 0.0001, 18_000_000, 100_000, 8),
    ("Devanahalli Airport Zone Plot", "Devanahalli, Bengaluru Rural",
     "Investment plot 6 km from Kempegowda International Airport, BIAAPA approved.",
     13.2480, 77.7120, 0.00015, 9_500_000, 50_000, -20),  # already ended
]


def _blob(lat: float, lng: float, half: float, rng: random.Random) -> dict:
    """An irregular 6–8 sided parcel shape around a centre point."""
    sides = rng.randint(6, 8)
    lng_scale = 1 / max(math.cos(math.radians(lat)), 0.2)
    ring = []
    for i in range(sides):
        angle = 2 * math.pi * i / sides + rng.uniform(-0.2, 0.2)
        r = half * rng.uniform(0.75, 1.15)
        ring.append([round(lng + r * math.cos(angle) * lng_scale, 6), round(lat + r * math.sin(angle), 6)])
    ring.append(ring[0])
    return {"type": "Polygon", "coordinates": [ring]}


def seed_demo_data(session: Session, anti_snipe_seconds: int = 120) -> bool:
    """Insert demo users, parcels and bids if there are no parcels yet."""
    if session.scalar(select(func.count(Parcel.id))):
        return False

    rng = random.Random(42)
    users: dict[str, User] = {}
    for name in DEMO_USERS:
        user = session.scalar(select(User).where(User.username == name))
        users[name] = user or services.register_user(session, name, f"{name}@example.com", DEMO_PASSWORD)

    now = utcnow()
    sellers = ["priya_estates", "greenacres", "rahul_k"]
    for i, (title, location, desc, lat, lng, half, price, inc, hours) in enumerate(DEMO_PARCELS):
        created = now - timedelta(days=3)
        end = now + timedelta(hours=hours)
        parcel = services.create_parcel(
            session,
            seller_id=users[sellers[i % len(sellers)]].id,
            title=title,
            description=desc,
            location=location,
            geometry=_blob(lat, lng, half, rng),
            starting_price=price,
            min_increment=inc,
            # create_parcel requires a future end; the ended demo parcel is moved back below.
            end_time=max(end, now + timedelta(hours=1)),
            max_days=365,
            now=now,
        )
        parcel.created_at = created

        bidders = [u for u in users.values() if u.id != parcel.seller_id]
        last_bid_time = min(end, now) - timedelta(minutes=10)
        n_bids = rng.randint(2, 7)
        t = created + timedelta(hours=2)
        step = (last_bid_time - t) / max(n_bids, 1)
        leader = None
        for _ in range(n_bids):
            bidder = rng.choice([b for b in bidders if b.id != leader])
            fresh = services.get_parcel(session, parcel.id)
            amount = services.minimum_next_bid(fresh) + inc * rng.randint(0, 4)
            services.place_bid(
                session, parcel_id=parcel.id, bidder_id=bidder.id, amount=amount,
                anti_snipe_seconds=anti_snipe_seconds, now=t,
            )
            leader = bidder.id
            t += step
        parcel = services.get_parcel(session, parcel.id)
        parcel.end_time = end  # restore the intended end (also sets the ended demo in the past)

    session.flush()
    return True
