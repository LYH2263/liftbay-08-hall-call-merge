from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.models import Building, CallTicket, DispatchLog, ElevatorCar


def seed_if_empty(db: Session) -> None:
    if db.scalar(select(Building.id).limit(1)):
        return
    b = Building(name="研发中心 A 座", floors=18)
    db.add(b)
    db.flush()
    cars = [
        ElevatorCar(building_id=b.id, label="A1", floor=3, direction="up", load=2, capacity=10),
        ElevatorCar(building_id=b.id, label="A2", floor=12, direction="down", load=4, capacity=10),
        ElevatorCar(building_id=b.id, label="A3", floor=1, direction="idle", load=0, capacity=8),
        ElevatorCar(building_id=b.id, label="A4", floor=8, direction="idle", load=8, capacity=8),
    ]
    db.add_all(cars)
    db.flush()
    c1 = CallTicket(building_id=b.id, floor=5, direction="up", passengers=2, status="waiting")
    c1b = CallTicket(building_id=b.id, floor=5, direction="up", passengers=3, status="waiting")
    c2 = CallTicket(building_id=b.id, floor=14, direction="down", passengers=1, status="waiting")
    c3 = CallTicket(
        building_id=b.id, floor=9, direction="up", passengers=3, status="assigned", assigned_car_id=cars[0].id, score="72.0"
    )
    db.add_all([c1, c1b, c2, c3])
    db.flush()
    db.add(DispatchLog(call_id=c3.id, car_id=cars[0].id, detail="同向优先派予 A1，评分 72.0"))

    # 同层同向合并失败场景：唯一轿厢剩余容量 4，2+3=5 接不住
    b2 = Building(name="实验塔 B 座", floors=6)
    db.add(b2)
    db.flush()
    db.add(
        ElevatorCar(building_id=b2.id, label="B1", floor=1, direction="idle", load=4, capacity=8)
    )
    db.flush()
    c4 = CallTicket(building_id=b2.id, floor=3, direction="up", passengers=2, status="waiting")
    c5 = CallTicket(building_id=b2.id, floor=3, direction="up", passengers=3, status="waiting")
    db.add_all([c4, c5])
    db.commit()
