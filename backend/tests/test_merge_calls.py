from sqlalchemy import select

from app.models.models import Building, CallTicket, ElevatorCar
from app.services.dispatch_engine import CarState, any_car_accepts


def _building(db, name="测试楼", floors=18):
    b = Building(name=name, floors=floors)
    db.add(b)
    db.flush()
    return b


def _car(db, building_id, label, load, capacity):
    c = ElevatorCar(building_id=building_id, label=label, floor=1,
                    direction="idle", load=load, capacity=capacity)
    db.add(c)
    db.flush()
    return c


def _call(db, building_id, floor=5, direction="up", passengers=1, status="waiting"):
    t = CallTicket(building_id=building_id, floor=floor, direction=direction,
                   passengers=passengers, status=status)
    db.add(t)
    db.flush()
    return t


def test_any_car_accepts():
    cars = [CarState(1, 1, "idle", load=4, capacity=8)]  # 剩余 4
    assert any_car_accepts(cars, 4) is True
    assert any_car_accepts(cars, 5) is False
    cars.append(CarState(2, 1, "idle", load=0, capacity=10))
    assert any_car_accepts(cars, 5) is True


def test_merge_fails_when_no_capacity_keeps_originals(client, session_factory):
    db = session_factory()
    b = _building(db, "容量失败楼")
    _car(db, b.id, "B1", load=4, capacity=8)  # 剩余容量 4
    t1 = _call(db, b.id, floor=3, direction="up", passengers=2)
    t2 = _call(db, b.id, floor=3, direction="up", passengers=3)
    id1, id2 = t1.id, t2.id
    db.commit()
    db.close()

    resp = client.post("/api/calls/merge", json={"call_ids": [id1, id2]})
    assert resp.status_code == 409

    db = session_factory()
    remaining = db.scalars(select(CallTicket).order_by(CallTicket.id)).all()
    assert len(remaining) == 2
    assert [t.passengers for t in remaining] == [2, 3]
    assert all(t.status == "waiting" for t in remaining)
    db.close()


def test_merge_success_leaves_single_waiting(client, session_factory):
    db = session_factory()
    b = _building(db, "容量足够楼")
    _car(db, b.id, "A1", load=2, capacity=10)  # 剩余容量 8
    t1 = _call(db, b.id, floor=5, direction="up", passengers=2)
    t2 = _call(db, b.id, floor=5, direction="up", passengers=3)
    id1, id2 = t1.id, t2.id
    db.commit()
    db.close()

    resp = client.post("/api/calls/merge", json={"call_ids": [id1, id2]})
    assert resp.status_code == 200
    merged = resp.json()
    assert merged["passengers"] == 5
    assert merged["status"] == "waiting"

    db = session_factory()
    waiting = db.scalars(
        select(CallTicket).where(CallTicket.status == "waiting")
    ).all()
    assert len(waiting) == 1
    assert waiting[0].id == min(id1, id2)
    assert waiting[0].passengers == 5

    # 再次查询仍是一行
    rows = client.get("/api/calls").json()
    assert len(rows) == 1
    assert rows[0]["passengers"] == 5
    db.close()


def test_merge_rejects_different_group(client, session_factory):
    db = session_factory()
    b1 = _building(db, "楼一")
    b2 = _building(db, "楼二")
    _car(db, b1.id, "X1", load=0, capacity=10)
    _car(db, b2.id, "Y1", load=0, capacity=10)
    same_floor_diff_dir = _call(db, b1.id, floor=5, direction="up", passengers=1)
    diff_dir = _call(db, b1.id, floor=5, direction="down", passengers=1)
    diff_floor = _call(db, b1.id, floor=6, direction="up", passengers=1)
    other_building = _call(db, b2.id, floor=5, direction="up", passengers=1)
    ids = (same_floor_diff_dir.id, diff_dir.id, diff_floor.id, other_building.id)
    db.commit()
    db.close()

    for pair in [[ids[0], ids[1]], [ids[0], ids[2]], [ids[0], ids[3]]]:
        assert client.post("/api/calls/merge", json={"call_ids": pair}).status_code == 400

    db = session_factory()
    assert len(db.scalars(select(CallTicket)).all()) == 4
    db.close()


def test_merged_call_dispatches_once_and_load_matches_congestion(client, session_factory):
    db = session_factory()
    b = _building(db, "对账楼")
    car = _car(db, b.id, "A1", load=2, capacity=10)  # 剩余 8，初始载荷 2
    t1 = _call(db, b.id, floor=5, direction="up", passengers=2)
    t2 = _call(db, b.id, floor=5, direction="up", passengers=3)
    id1, id2, car_id = t1.id, t2.id, car.id
    db.commit()
    db.close()

    assert client.post("/api/calls/merge", json={"call_ids": [id1, id2]}).status_code == 200

    # 拥堵按合并后人数计
    cong = client.get("/api/congestion").json()
    assert cong == [{"floor": 5, "passengers": 5}]

    # 派工一次派合并单
    merged_id = min(id1, id2)
    resp = client.post("/api/dispatch", json={"call_id": merged_id})
    assert resp.status_code == 200
    assigned = resp.json()
    assert assigned["assigned_car_id"] == car_id
    assert assigned["status"] == "assigned"

    # 被合并掉的单不能再派
    gone_id = max(id1, id2)
    assert client.post("/api/dispatch", json={"call_id": gone_id}).status_code == 404

    # 轿厢载荷一次加上总人数：2 + 5 = 7
    db = session_factory()
    car_row = db.get(ElevatorCar, car_id)
    assert car_row.load == 7
    assert client.get("/api/congestion").json() == []
    db.close()
