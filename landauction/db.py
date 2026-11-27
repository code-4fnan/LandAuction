"""Database engine, session factory and ORM models.

SQLite is the default (a single file under ``data/``, nothing to install).
Point ``DATABASE_URL`` at Postgres (e.g. a free Neon/Supabase database) when
you need data to survive Streamlit Cloud restarts. The models are portable
across both.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Iterator

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
    create_engine,
    event,
)
from sqlalchemy.engine import Engine
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    Session,
    mapped_column,
    relationship,
    sessionmaker,
)


def utcnow() -> datetime:
    """Naive UTC timestamp; every datetime in the database is naive UTC."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(30), unique=True, index=True)
    email: Mapped[str] = mapped_column(String(254), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Parcel(Base):
    """A land parcel listed for auction. Money is stored in whole currency units."""

    __tablename__ = "parcels"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text, default="")
    location: Mapped[str] = mapped_column(String(120), default="")
    seller_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)

    boundary_geojson: Mapped[str] = mapped_column(Text)  # GeoJSON Polygon geometry
    centroid_lat: Mapped[float]
    centroid_lng: Mapped[float]
    area_sqm: Mapped[float]

    starting_price: Mapped[int] = mapped_column(BigInteger)
    min_increment: Mapped[int] = mapped_column(BigInteger)
    current_price: Mapped[int] = mapped_column(BigInteger)
    leader_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    bid_count: Mapped[int] = mapped_column(Integer, default=0)

    end_time: Mapped[datetime] = mapped_column(DateTime, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    # Eager-loaded so objects stay usable after their session closes.
    seller: Mapped[User] = relationship(foreign_keys=[seller_id], lazy="joined")
    leader: Mapped[User | None] = relationship(foreign_keys=[leader_id], lazy="joined")


class Bid(Base):
    __tablename__ = "bids"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    parcel_id: Mapped[int] = mapped_column(ForeignKey("parcels.id"), index=True)
    bidder_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    amount: Mapped[int] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    bidder: Mapped[User] = relationship(lazy="joined")


class ParcelPhoto(Base):
    """A seller-uploaded photo, stored in the database so it survives redeploys with Postgres."""

    __tablename__ = "parcel_photos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    parcel_id: Mapped[int] = mapped_column(ForeignKey("parcels.id"), index=True)
    data: Mapped[bytes] = mapped_column(LargeBinary)  # JPEG, max 1600 px
    thumb: Mapped[bytes] = mapped_column(LargeBinary)  # JPEG, 360x240
    width: Mapped[int] = mapped_column(Integer)
    height: Mapped[int] = mapped_column(Integer)
    caption: Mapped[str] = mapped_column(String(120), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Watch(Base):
    __tablename__ = "watchlist"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    parcel_id: Mapped[int] = mapped_column(ForeignKey("parcels.id"), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


def _configure_sqlite(engine: Engine) -> None:
    @event.listens_for(engine, "connect")
    def _pragmas(dbapi_conn, _record):  # pragma: no cover - trivial
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")  # readers don't block the writer
        cur.execute("PRAGMA busy_timeout=5000")  # wait instead of failing on lock
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()


@lru_cache(maxsize=4)
def get_engine(database_url: str) -> Engine:
    if database_url.startswith("sqlite"):
        db_path = database_url.split("///", 1)[-1]
        if db_path and db_path != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        engine = create_engine(database_url, connect_args={"check_same_thread": False})
        _configure_sqlite(engine)
    else:
        # Hosted Postgres (Neon, Supabase, ...) hands out postgres:// or postgresql:// URLs;
        # use the psycopg 3 driver for both. Recycle idle connections the host may drop.
        for prefix in ("postgres://", "postgresql://"):
            if database_url.startswith(prefix):
                database_url = "postgresql+psycopg://" + database_url[len(prefix):]
        engine = create_engine(database_url, pool_pre_ping=True, pool_recycle=300)
    Base.metadata.create_all(engine)
    return engine


@lru_cache(maxsize=4)
def _session_factory(database_url: str) -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(database_url), expire_on_commit=False)


@contextmanager
def session_scope(database_url: str) -> Iterator[Session]:
    """Open a session; commit on success, roll back on error."""
    session = _session_factory(database_url)()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
