from __future__ import annotations

import threading
from datetime import timedelta

import pytest

from landauction import fmt, geo, services
from landauction.db import session_scope, utcnow
from landauction.seed import seed_demo_data

SQUARE = {  # ~111 m x 111 m near the equator
    "type": "Polygon",
    "coordinates": [[[0, 0], [0.001, 0], [0.001, 0.001], [0, 0.001], [0, 0]]],
}


@pytest.fixture()
def db_url(tmp_path):
    return f"sqlite:///{(tmp_path / 'test.db').as_posix()}"


@pytest.fixture()
def world(db_url):
    """A seller, two bidders and one live parcel (start 1000, increment 100)."""
    with session_scope(db_url) as s:
        seller = services.register_user(s, "seller", "seller@x.com", "password123")
        alice = services.register_user(s, "alice", "alice@x.com", "password123")
        bob = services.register_user(s, "bob", "bob@x.com", "password123")
        parcel = services.create_parcel(
            s, seller_id=seller.id, title="Test plot", geometry=SQUARE,
            starting_price=1000, min_increment=100, end_time=utcnow() + timedelta(days=1),
        )
        return db_url, seller.id, alice.id, bob.id, parcel.id


# ---------------------------------------------------------------- geometry


def test_area_of_small_square_near_equator():
    area = geo.ring_area_sqm(geo.outer_ring(SQUARE))
    assert 12_200 < area < 12_500  # 111.3 m * 110.6 m


def test_outer_ring_closes_and_validates():
    open_ring = {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1]]]}
    ring = geo.outer_ring(open_ring)
    assert ring[0] == ring[-1]
    with pytest.raises(geo.GeometryError):
        geo.outer_ring({"type": "Point", "coordinates": [0, 0]})
    with pytest.raises(geo.GeometryError):
        geo.outer_ring({"type": "Polygon", "coordinates": [[[0, 0], [1, 1], [0, 0]]]})


def test_point_in_ring():
    ring = geo.outer_ring(SQUARE)
    assert geo.point_in_ring(0.0005, 0.0005, ring)
    assert not geo.point_in_ring(0.002, 0.0005, ring)


# ---------------------------------------------------------------- formatting


@pytest.mark.parametrize(
    "n,expected",
    [(0, "0"), (999, "999"), (1000, "1,000"), (123456, "1,23,456"), (12345678, "1,23,45,678")],
)
def test_indian_grouping(n, expected):
    assert fmt.group_indian(n) == expected


def test_money_compact():
    assert fmt.money_compact(4_500_000) == "₹45.0 L"
    assert fmt.money_compact(18_000_000) == "₹1.80 Cr"


# ---------------------------------------------------------------- accounts


def test_register_and_login(db_url):
    with session_scope(db_url) as s:
        services.register_user(s, "Asha_1", "asha@x.com", "longpassword")
    with session_scope(db_url) as s:
        assert services.authenticate(s, "asha_1", "longpassword") is not None  # case-insensitive
        assert services.authenticate(s, "Asha_1", "wrong-password") is None
        assert services.authenticate(s, "nobody", "longpassword") is None


@pytest.mark.parametrize(
    "username,email,password",
    [("ab", "a@x.com", "password1"), ("good_name", "bad-email", "password1"), ("good_name", "a@x.com", "short")],
)
def test_register_validation(db_url, username, email, password):
    with session_scope(db_url) as s, pytest.raises(services.ValidationError):
        services.register_user(s, username, email, password)


def test_duplicate_username_rejected(db_url):
    with session_scope(db_url) as s:
        services.register_user(s, "asha", "asha@x.com", "longpassword")
    with session_scope(db_url) as s, pytest.raises(services.ValidationError, match="username"):
        services.register_user(s, "ASHA", "other@x.com", "longpassword")


# ---------------------------------------------------------------- listings


def test_create_parcel_validation(world):
    db_url, seller, *_ = world
    with session_scope(db_url) as s:
        with pytest.raises(services.ValidationError, match="5 minutes"):
            services.create_parcel(s, seller_id=seller, title="Plot", geometry=SQUARE,
                                   starting_price=10, min_increment=1, end_time=utcnow())
        with pytest.raises(services.ValidationError, match="increment"):
            services.create_parcel(s, seller_id=seller, title="Plot", geometry=SQUARE,
                                   starting_price=10, min_increment=50,
                                   end_time=utcnow() + timedelta(days=1))


# ---------------------------------------------------------------- bidding


def bid(db_url, parcel_id, bidder, amount, **kw):
    with session_scope(db_url) as s:
        return services.place_bid(s, parcel_id=parcel_id, bidder_id=bidder, amount=amount, **kw)


def test_first_bid_must_meet_starting_price(world):
    db_url, _, alice, _, pid = world
    with pytest.raises(services.BidRejected, match="too low"):
        bid(db_url, pid, alice, 999)
    bid(db_url, pid, alice, 1000)  # equal to the starting price is allowed


def test_later_bids_must_add_increment(world):
    db_url, _, alice, bob, pid = world
    bid(db_url, pid, alice, 1000)
    with pytest.raises(services.BidRejected, match="too low"):
        bid(db_url, pid, bob, 1099)
    bid(db_url, pid, bob, 1100)
    with session_scope(db_url) as s:
        p = services.get_parcel(s, pid)
        assert (p.current_price, p.leader_id, p.bid_count) == (1100, bob, 2)
        assert services.minimum_next_bid(p) == 1200
        assert [b.amount for b in services.bid_history(s, pid)] == [1100, 1000]


def test_seller_and_leader_cannot_bid(world):
    db_url, seller, alice, _, pid = world
    with pytest.raises(services.BidRejected, match="own listing"):
        bid(db_url, pid, seller, 5000)
    bid(db_url, pid, alice, 1000)
    with pytest.raises(services.BidRejected, match="already the highest"):
        bid(db_url, pid, alice, 2000)


def test_ended_auction_rejects_bids(world):
    db_url, _, alice, _, pid = world
    with pytest.raises(services.BidRejected, match="ended"):
        bid(db_url, pid, alice, 5000, now=utcnow() + timedelta(days=2))


def test_anti_snipe_extends_end_time(world):
    db_url, _, alice, _, pid = world
    with session_scope(db_url) as s:
        end = services.get_parcel(s, pid).end_time
    late = end - timedelta(seconds=30)
    result = bid(db_url, pid, alice, 1000, now=late, anti_snipe_seconds=120)
    assert result.extended
    assert result.end_time == late + timedelta(seconds=120)


def test_concurrent_equal_bids_only_one_wins(world):
    db_url, _, alice, bob, pid = world
    outcomes: list[str] = []
    barrier = threading.Barrier(2)

    def go(user):
        barrier.wait()
        try:
            bid(db_url, pid, user, 1000)
            outcomes.append("ok")
        except services.BidRejected:
            outcomes.append("rejected")

    threads = [threading.Thread(target=go, args=(u,)) for u in (alice, bob)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(outcomes) == ["ok", "rejected"]
    with session_scope(db_url) as s:
        assert services.get_parcel(s, pid).bid_count == 1


def test_my_bids_outcomes(world):
    db_url, _, alice, bob, pid = world
    bid(db_url, pid, alice, 1000)
    bid(db_url, pid, bob, 1100)
    with session_scope(db_url) as s:
        assert services.my_bids(s, alice)[0].outcome == "outbid"
        assert services.my_bids(s, bob)[0].outcome == "winning"
        later = utcnow() + timedelta(days=2)
        assert services.my_bids(s, bob, now=later)[0].outcome == "won"
        assert services.my_bids(s, alice, now=later)[0].outcome == "lost"


def test_watchlist_toggle(world):
    db_url, _, alice, _, pid = world
    with session_scope(db_url) as s:
        assert services.toggle_watch(s, alice, pid) is True
    with session_scope(db_url) as s:
        assert [p.id for p in services.watched_parcels(s, alice)] == [pid]
        assert services.toggle_watch(s, alice, pid) is False


# ---------------------------------------------------------------- seed


def test_seed_is_idempotent(db_url):
    with session_scope(db_url) as s:
        assert seed_demo_data(s) is True
    with session_scope(db_url) as s:
        assert seed_demo_data(s) is False
        parcels = services.list_parcels(s)
        assert len(parcels) == 6
        statuses = {services.parcel_status(p) for p in parcels}
        assert {"live", "ending_soon", "ended"} <= statuses
        assert all(p.bid_count >= 2 for p in parcels)


# ---------------------------------------------------------------- photos


def _png(width=800, height=600) -> bytes:
    import io

    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (width, height), (40, 120, 60)).save(buf, format="PNG")
    return buf.getvalue()


def test_seller_can_add_and_remove_photos(world):
    db_url, seller, alice, _, pid = world
    with session_scope(db_url) as s:
        photo = services.add_photo(s, parcel_id=pid, user_id=seller, raw=_png(3000, 2000), caption="Front gate")
        assert (photo.width, photo.height) == (1600, 1067)  # downscaled
        assert photo.data[:2] == b"\xff\xd8"  # re-encoded as JPEG
        photo_id = photo.id
    with session_scope(db_url) as s:
        assert services.photo_counts(s) == {pid: 1}
        with pytest.raises(services.ValidationError, match="Only the seller"):
            services.delete_photo(s, photo_id=photo_id, user_id=alice)
    with session_scope(db_url) as s:
        services.delete_photo(s, photo_id=photo_id, user_id=seller)
    with session_scope(db_url) as s:
        assert services.list_photos(s, pid) == []


def test_photo_rules(world):
    db_url, seller, alice, _, pid = world
    with session_scope(db_url) as s:
        with pytest.raises(services.ValidationError, match="Only the seller"):
            services.add_photo(s, parcel_id=pid, user_id=alice, raw=_png())
        with pytest.raises(services.ValidationError, match="valid image"):
            services.add_photo(s, parcel_id=pid, user_id=seller, raw=b"<script>alert(1)</script>")
        for _ in range(services.MAX_PHOTOS):
            services.add_photo(s, parcel_id=pid, user_id=seller, raw=_png(100, 100))
        with pytest.raises(services.ValidationError, match="at most"):
            services.add_photo(s, parcel_id=pid, user_id=seller, raw=_png(100, 100))
