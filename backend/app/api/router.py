from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.models import Building, CallTicket, DispatchLog, ElevatorCar
from app.schemas.schemas import (
    BuildingOut,
    CallCreate,
    CallOut,
    CarOut,
    CongestionFloor,
    DispatchRequest,
    LogOut,
    MergeRequest,
)
from app.services.dispatch_engine import (
    CallRequest,
    CarState,
    any_car_accepts,
    congestion_by_floor,
    pick_car,
)

api_router = APIRouter()


@api_router.get("/health")
def health():
    return {"status": "ok"}


@api_router.get("/buildings", response_model=list[BuildingOut])
def buildings(db: Session = Depends(get_db)):
    return db.scalars(select(Building).order_by(Building.id)).all()


@api_router.get("/cars", response_model=list[CarOut])
def cars(db: Session = Depends(get_db)):
    return db.scalars(select(ElevatorCar).order_by(ElevatorCar.id)).all()


@api_router.get("/calls", response_model=list[CallOut])
def calls(db: Session = Depends(get_db)):
    return db.scalars(select(CallTicket).order_by(CallTicket.id.desc())).all()


@api_router.post("/calls", response_model=CallOut)
def create_call(body: CallCreate, db: Session = Depends(get_db)):
    b = db.get(Building, body.building_id)
    if not b:
        raise HTTPException(404, "楼栋不存在")
    if body.floor > b.floors:
        raise HTTPException(400, "楼层超出")
    if body.direction not in ("up", "down"):
        raise HTTPException(400, "方向无效")
    ticket = CallTicket(
        building_id=body.building_id,
        floor=body.floor,
        direction=body.direction,
        passengers=body.passengers,
    )
    db.add(ticket)
    db.commit()
    db.refresh(ticket)
    return ticket


@api_router.post("/calls/merge", response_model=CallOut)
def merge_calls(body: MergeRequest, db: Session = Depends(get_db)):
    call_ids = list(dict.fromkeys(body.call_ids))
    if len(call_ids) < 2:
        raise HTTPException(400, "至少选择两笔呼梯才能合并")
    tickets = [db.get(CallTicket, cid) for cid in call_ids]
    if any(t is None for t in tickets):
        raise HTTPException(404, "呼梯不存在")
    if any(t.status != "waiting" for t in tickets):
        raise HTTPException(400, "仅 waiting 状态的呼梯可以合并")
    first = tickets[0]
    if any(
        (t.building_id, t.floor, t.direction)
        != (first.building_id, first.floor, first.direction)
        for t in tickets[1:]
    ):
        raise HTTPException(400, "只能合并同楼栋、同候梯层、同方向的呼梯")

    total_passengers = sum(t.passengers for t in tickets)
    car_rows = db.scalars(
        select(ElevatorCar).where(ElevatorCar.building_id == first.building_id)
    ).all()
    cars = [CarState(c.id, c.floor, c.direction, c.load, c.capacity) for c in car_rows]
    if not any_car_accepts(cars, total_passengers):
        # 合并后没有任何轿厢接得住：保持原多笔不变
        raise HTTPException(409, "合并后总人数超出全部轿厢剩余容量，合并失败")

    survivor = min(tickets, key=lambda t: t.id)
    for t in tickets:
        if t is not survivor:
            db.delete(t)
    survivor.passengers = total_passengers
    db.commit()
    db.refresh(survivor)
    return survivor


@api_router.post("/dispatch", response_model=CallOut)
def dispatch(body: DispatchRequest, db: Session = Depends(get_db)):
    ticket = db.get(CallTicket, body.call_id)
    if not ticket:
        raise HTTPException(404, "呼梯不存在")
    if ticket.status != "waiting":
        raise HTTPException(400, "呼梯已处理")
    car_rows = db.scalars(
        select(ElevatorCar).where(ElevatorCar.building_id == ticket.building_id)
    ).all()
    cars = [
        CarState(c.id, c.floor, c.direction, c.load, c.capacity) for c in car_rows
    ]
    call = CallRequest(ticket.id, ticket.floor, ticket.direction, ticket.passengers)
    best = pick_car(cars, call)
    if best is None:
        db.add(DispatchLog(call_id=ticket.id, car_id=None, detail="全部轿厢满员，拒绝派工"))
        ticket.status = "rejected"
        db.commit()
        db.refresh(ticket)
        raise HTTPException(409, "无可用轿厢（满员）")
    car = db.get(ElevatorCar, best.car_id)
    assert car
    ticket.status = "assigned"
    ticket.assigned_car_id = car.id
    ticket.score = f"{best.score:.1f}"
    car.load += ticket.passengers
    car.floor = ticket.floor
    car.direction = ticket.direction
    db.add(
        DispatchLog(
            call_id=ticket.id,
            car_id=car.id,
            detail=f"派予 {car.label}，评分 {best.score:.1f}（同向/距离综合）",
        )
    )
    db.commit()
    db.refresh(ticket)
    return ticket


@api_router.get("/replay", response_model=list[LogOut])
def replay(db: Session = Depends(get_db)):
    return db.scalars(select(DispatchLog).order_by(DispatchLog.id.desc())).all()


@api_router.get("/congestion", response_model=list[CongestionFloor])
def congestion(db: Session = Depends(get_db)):
    waiting = db.scalars(select(CallTicket).where(CallTicket.status == "waiting")).all()
    counts = congestion_by_floor(
        [CallRequest(c.id, c.floor, c.direction, c.passengers) for c in waiting]
    )
    return [
        CongestionFloor(floor=f, passengers=p)
        for f, p in sorted(counts.items(), key=lambda x: -x[1])
    ]
