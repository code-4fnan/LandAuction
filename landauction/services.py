"""Business rules: accounts, listings, bidding, watchlist and user activity.

Every function takes an open SQLAlchemy ``Session``; the caller owns the
transaction (see :func:`landauction.db.session_scope`).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Literal

import bcrypt
from sqlalchemy import and_, case, delete, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from . import fmt, geo, images
from .config import settings
from .db import Bid, Parcel, ParcelPhoto, User, Watch, utcnow

MAX_PRICE = 10**12  # sanity cap on any amount
ENDING_SOON = timedelta(hours=1)

USERNAME_RE = re.compile(r"^[A-Za-z0-9_]{3,30}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

Status = Literal["live", "ending_soon", "ended"]


class ValidationError(ValueError):
    """Raised with a user-facing message when input breaks a rule."""


class BidRejected(ValueError):
    """Raised with a user-facing message when a bid is not accepted."""


# --------------------------------------------------------------------------- accounts

# Used to keep login timing similar whether or not the username exists.
_DUMMY_HASH = bcrypt.hashpw(b"not-a-real-password", bcrypt.gensalt())


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("ascii")


def check_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("ascii"))
    except ValueError:
        return False


def register_user(session: Session, username: str, email: str, password: str) -> User:
    username, email = username.strip(), email.strip().lower()
    if not USERNAME_RE.match(username):
        raise ValidationError("Username must be 3–30 characters: letters, numbers or _.")
    if not EMAIL_RE.match(email):
        raise ValidationError("Enter a valid email address.")
    if len(password) < 8:
        raise ValidationError("Password must be at least 8 characters.")
    if len(password.encode("utf-8")) > 72:
        raise ValidationError("Password must be at most 72 bytes.")

    taken = session.scalar(
        select(User).where(or_(func.lower(User.username) == username.lower(), User.email == email))
    )
    if taken:
        field = "username" if taken.username.lower() == username.lower() else "email"
        raise ValidationError(f"That {field} is already registered.")

    user = User(username=username, email=email, password_hash=hash_password(password))
    session.add(user)
    try:
        session.flush()
    except IntegrityError as exc:  # lost a race with a simultaneous sign-up
        session.rollback()
        raise ValidationError("That username or email is already registered.") from exc
    return user


def authenticate(session: Session, username: str, password: str) -> User | None:
    user = session.scalar(select(User).where(func.lower(User.username) == username.strip().lower()))
    if user is None:
        bcrypt.checkpw(b"x", _DUMMY_HASH)
        return None
    return user if check_password(password, user.password_hash) else None


# --------------------------------------------------------------------------- parcels


def parcel_status(parcel: Parcel, now: datetime | None = None) -> Status:
    now = now or utcnow()
    if parcel.end_time <= now:
        return "ended"
    if parcel.end_time - now <= ENDING_SOON:
        return "ending_soon"
    return "live"


def minimum_next_bid(parcel: Parcel) -> int:
    if parcel.bid_count == 0:
        return parcel.starting_price
    return parcel.current_price + parcel.min_increment


def parcel_ring(parcel: Parcel) -> geo.Ring:
    return geo.outer_ring(json.loads(parcel.boundary_geojson))


def create_parcel(
    session: Session,
    *,
    seller_id: int,
    title: str,
    geometry: dict[str, Any],
    starting_price: int,
    min_increment: int,
    end_time: datetime,
    description: str = "",
    location: str = "",
    max_days: int = 60,
    now: datetime | None = None,
) -> Parcel:
    now = now or utcnow()
    title = title.strip()
    if not 3 <= len(title) <= 120:
        raise ValidationError("Title must be 3–120 characters.")
    if len(description) > 2000:
        raise ValidationError("Description must be at most 2000 characters.")
    if not 0 < starting_price <= MAX_PRICE:
        raise ValidationError("Starting price must be greater than zero.")
    if not 0 < min_increment <= starting_price:
        raise ValidationError("Minimum increment must be above zero and not exceed the starting price.")
    if end_time <= now + timedelta(minutes=5):
        raise ValidationError("The auction must run for at least 5 minutes.")
    if end_time > now + timedelta(days=max_days):
        raise ValidationError(f"The auction can run for at most {max_days} days.")

    try:
        ring = geo.outer_ring(geometry)
    except geo.GeometryError as exc:
        raise ValidationError(str(exc)) from exc
    area = geo.ring_area_sqm(ring)
    if area < geo.MIN_PARCEL_AREA_SQM:
        raise ValidationError("The drawn boundary is too small. Zoom in and draw the parcel outline.")
    if area > geo.MAX_PARCEL_AREA_SQM:
        raise ValidationError("The drawn boundary is larger than 100 km². Draw a single parcel.")
    lat, lng = geo.ring_centroid(ring)

    parcel = Parcel(
        title=title,
        description=description.strip(),
        location=location.strip(),
        seller_id=seller_id,
        boundary_geojson=json.dumps({"type": "Polygon", "coordinates": [ring]}),
        centroid_lat=lat,
        centroid_lng=lng,
        area_sqm=area,
        starting_price=int(starting_price),
        min_increment=int(min_increment),
        current_price=int(starting_price),
        bid_count=0,
        end_time=end_time,
        created_at=now,
    )
    session.add(parcel)
    session.flush()
    return parcel


def get_parcel(session: Session, parcel_id: int) -> Parcel | None:
    return session.get(Parcel, parcel_id, populate_existing=True)


SortKey = Literal["ending", "newest", "price_high", "price_low", "bids"]


def list_parcels(
    session: Session,
    *,
    search: str = "",
    status: Literal["all", "active", "ended"] = "all",
    sort: SortKey = "ending",
    now: datetime | None = None,
) -> list[Parcel]:
    now = now or utcnow()
    stmt = select(Parcel)
    if search.strip():
        like = f"%{search.strip().lower()}%"
        stmt = stmt.where(
            or_(
                func.lower(Parcel.title).like(like),
                func.lower(Parcel.location).like(like),
                func.lower(Parcel.description).like(like),
            )
        )
    if status == "active":
        stmt = stmt.where(Parcel.end_time > now)
    elif status == "ended":
        stmt = stmt.where(Parcel.end_time <= now)

    order = {
        "ending": Parcel.end_time.asc(),
        "newest": Parcel.created_at.desc(),
        "price_high": Parcel.current_price.desc(),
        "price_low": Parcel.current_price.asc(),
        "bids": Parcel.bid_count.desc(),
    }[sort]
    parcels = list(session.scalars(stmt.order_by(order, Parcel.id)).unique())
    if sort == "ending":
        # Active auctions soonest-first, then ended ones most-recent-first.
        active = [p for p in parcels if p.end_time > now]
        ended = [p for p in reversed(parcels) if p.end_time <= now]
        parcels = active + ended
    return parcels


# --------------------------------------------------------------------------- bidding


@dataclass(frozen=True)
class BidResult:
    amount: int
    end_time: datetime
    extended: bool


def place_bid(
    session: Session,
    *,
    parcel_id: int,
    bidder_id: int,
    amount: int,
    anti_snipe_seconds: int = 120,
    now: datetime | None = None,
) -> BidResult:
    """Place a bid atomically.

    The price check and the update happen in one conditional ``UPDATE``, so two
    people bidding at the same instant can't both win: the database applies one
    and the other's WHERE clause no longer matches. A bid in the final
    ``anti_snipe_seconds`` pushes the end time out so others can respond.
    """
    now = now or utcnow()
    try:
        amount = int(amount)
    except (TypeError, ValueError) as exc:
        raise BidRejected("Enter a whole-number bid amount.") from exc
    if not 0 < amount <= MAX_PRICE:
        raise BidRejected("Enter a valid bid amount.")

    snipe_cutoff = now + timedelta(seconds=anti_snipe_seconds)
    stmt = (
        update(Parcel)
        .where(
            Parcel.id == parcel_id,
            Parcel.end_time > now,
            Parcel.seller_id != bidder_id,
            or_(Parcel.leader_id.is_(None), Parcel.leader_id != bidder_id),
            or_(
                and_(Parcel.bid_count == 0, Parcel.starting_price <= amount),
                and_(Parcel.bid_count > 0, Parcel.current_price + Parcel.min_increment <= amount),
            ),
        )
        .values(
            current_price=amount,
            leader_id=bidder_id,
            bid_count=Parcel.bid_count + 1,
            end_time=case((Parcel.end_time < snipe_cutoff, snipe_cutoff), else_=Parcel.end_time),
        )
        .execution_options(synchronize_session=False)
    )
    if session.execute(stmt).rowcount != 1:
        _raise_bid_rejection(session, parcel_id, bidder_id, now)

    session.add(Bid(parcel_id=parcel_id, bidder_id=bidder_id, amount=amount, created_at=now))
    session.flush()
    parcel = get_parcel(session, parcel_id)
    assert parcel is not None
    return BidResult(amount=amount, end_time=parcel.end_time, extended=parcel.end_time == snipe_cutoff)


def _raise_bid_rejection(session: Session, parcel_id: int, bidder_id: int, now: datetime) -> None:
    parcel = get_parcel(session, parcel_id)
    if parcel is None:
        raise BidRejected("This auction no longer exists.")
    if parcel.end_time <= now:
        raise BidRejected("This auction has ended.")
    if parcel.seller_id == bidder_id:
        raise BidRejected("You can't bid on your own listing.")
    if parcel.leader_id == bidder_id:
        raise BidRejected("You're already the highest bidder.")
    raise BidRejected(
        f"Bid too low. The minimum bid is now {fmt.money(minimum_next_bid(parcel), settings.currency_symbol)}."
    )


def bid_history(session: Session, parcel_id: int, limit: int = 200) -> list[Bid]:
    stmt = select(Bid).where(Bid.parcel_id == parcel_id).order_by(Bid.created_at.desc(), Bid.id.desc())
    return list(session.scalars(stmt.limit(limit)).unique())


# --------------------------------------------------------------------------- photos

MAX_PHOTOS = 8


def add_photo(session: Session, *, parcel_id: int, user_id: int, raw: bytes, caption: str = "") -> ParcelPhoto:
    parcel = get_parcel(session, parcel_id)
    if parcel is None:
        raise ValidationError("This listing no longer exists.")
    if parcel.seller_id != user_id:
        raise ValidationError("Only the seller can add photos to a listing.")
    count = session.scalar(select(func.count(ParcelPhoto.id)).where(ParcelPhoto.parcel_id == parcel_id))
    if (count or 0) >= MAX_PHOTOS:
        raise ValidationError(f"A listing can have at most {MAX_PHOTOS} photos.")
    try:
        img = images.process(raw)
    except images.ImageError as exc:
        raise ValidationError(str(exc)) from exc
    photo = ParcelPhoto(parcel_id=parcel_id, data=img.full, thumb=img.thumb, width=img.width,
                        height=img.height, caption=caption.strip()[:120])
    session.add(photo)
    session.flush()
    return photo


def list_photos(session: Session, parcel_id: int) -> list[ParcelPhoto]:
    stmt = select(ParcelPhoto).where(ParcelPhoto.parcel_id == parcel_id).order_by(ParcelPhoto.id)
    return list(session.scalars(stmt))


def delete_photo(session: Session, *, photo_id: int, user_id: int) -> None:
    photo = session.get(ParcelPhoto, photo_id)
    if photo is None:
        return
    parcel = get_parcel(session, photo.parcel_id)
    if parcel is None or parcel.seller_id != user_id:
        raise ValidationError("Only the seller can remove photos from a listing.")
    session.delete(photo)
    session.flush()


def photo_counts(session: Session) -> dict[int, int]:
    rows = session.execute(select(ParcelPhoto.parcel_id, func.count(ParcelPhoto.id)).group_by(ParcelPhoto.parcel_id))
    return {pid: int(n) for pid, n in rows}


# --------------------------------------------------------------------------- watchlist


def is_watching(session: Session, user_id: int, parcel_id: int) -> bool:
    return session.get(Watch, (user_id, parcel_id)) is not None


def toggle_watch(session: Session, user_id: int, parcel_id: int) -> bool:
    """Flip watch state; returns the new state."""
    if is_watching(session, user_id, parcel_id):
        session.execute(delete(Watch).where(Watch.user_id == user_id, Watch.parcel_id == parcel_id))
        return False
    session.add(Watch(user_id=user_id, parcel_id=parcel_id))
    session.flush()
    return True


def watched_parcels(session: Session, user_id: int) -> list[Parcel]:
    stmt = select(Parcel).join(Watch, Watch.parcel_id == Parcel.id).where(Watch.user_id == user_id)
    return list(session.scalars(stmt.order_by(Parcel.end_time)).unique())


# --------------------------------------------------------------------------- activity


@dataclass(frozen=True)
class BidActivity:
    parcel: Parcel
    my_max_bid: int
    my_bid_count: int
    outcome: Literal["winning", "outbid", "won", "lost"]


def my_bids(session: Session, user_id: int, now: datetime | None = None) -> list[BidActivity]:
    now = now or utcnow()
    rows = session.execute(
        select(Bid.parcel_id, func.max(Bid.amount), func.count(Bid.id))
        .where(Bid.bidder_id == user_id)
        .group_by(Bid.parcel_id)
    ).all()
    out: list[BidActivity] = []
    for parcel_id, max_bid, count in rows:
        parcel = get_parcel(session, parcel_id)
        if parcel is None:
            continue
        leading = parcel.leader_id == user_id
        ended = parcel.end_time <= now
        outcome = ("won" if leading else "lost") if ended else ("winning" if leading else "outbid")
        out.append(BidActivity(parcel, int(max_bid), int(count), outcome))
    order = {"winning": 0, "outbid": 1, "won": 2, "lost": 3}
    return sorted(out, key=lambda a: (order[a.outcome], a.parcel.end_time))


def my_listings(session: Session, user_id: int) -> list[Parcel]:
    stmt = select(Parcel).where(Parcel.seller_id == user_id).order_by(Parcel.created_at.desc())
    return list(session.scalars(stmt).unique())


@dataclass(frozen=True)
class MarketStats:
    active: int
    ending_soon: int
    total_bids: int
    active_value: int
    bidders: int


def market_stats(session: Session, now: datetime | None = None) -> MarketStats:
    now = now or utcnow()
    active, value = session.execute(
        select(func.count(Parcel.id), func.coalesce(func.sum(Parcel.current_price), 0)).where(
            Parcel.end_time > now
        )
    ).one()
    soon = session.scalar(
        select(func.count(Parcel.id)).where(Parcel.end_time > now, Parcel.end_time <= now + ENDING_SOON)
    )
    total_bids, bidders = session.execute(
        select(func.count(Bid.id), func.count(func.distinct(Bid.bidder_id)))
    ).one()
    return MarketStats(int(active), int(soon or 0), int(total_bids), int(value), int(bidders))
