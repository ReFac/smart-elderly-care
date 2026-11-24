"""Create the illustrated two-building demo in a new encrypted database."""

import argparse
from getpass import getpass
from pathlib import Path
import os
import secrets

from platform_core import care_areas, facility, scheduled_work
from platform_core.store import Store


WEEKLY = {
    "早餐": (
        "小米粥 水煮蛋 馒头", "南瓜粥 蒸蛋 花卷", "大米粥 鸡蛋羹 豆沙包", "山药粥 煮鸡蛋 馒头",
        "八宝粥 豆浆 花卷", "小米粥 蒸南瓜 鸡蛋羹", "蔬菜粥 水煮蛋 包子",
    ),
    "午餐": (
        "米饭 清蒸鱼 炒青菜 冬瓜汤", "米饭 土豆炖鸡 蒸豆腐 白菜汤", "米饭 番茄炒蛋 炒青菜 冬瓜汤",
        "米饭 萝卜炖牛肉 炒白菜 豆腐汤", "米饭 清蒸鱼 炒西葫芦 南瓜汤", "米饭 蒸肉饼 炒青菜 番茄汤",
        "米饭 香菇炖鸡 清炒白菜 冬瓜汤",
    ),
    "晚餐": (
        "鸡丝面 蒸南瓜 炒青菜", "红薯粥 花卷 青菜豆腐", "小米粥 馒头 番茄豆腐",
        "鸡蛋面 蒸山药 炒青菜", "蔬菜粥 蒸蛋 花卷", "大米粥 菜包 蒸南瓜", "青菜面 清蒸豆腐 红薯",
    ),
}


def structure(store, token, command):
    command("facility.addBuilding", name="康复楼", campusId=facility.HOME_CAMPUS)
    buildings = care_areas.read(store, token)["buildings"]
    annex = next(b["id"] for b in buildings if b["name"] == "康复楼")
    for number in (1, 2):
        command("facility.addFloor", buildingId=annex, number=number)
    for floor in care_areas.read(store, token, annex)["floors"]:
        number = floor["number"]
        command("facility.addRoom", floorId=floor["id"], number=f"{number}01",
                ward=f"康复楼 {number} 层", bedCount=2, dailyRate=68)
    directory = store.snapshot(token)["data"]["bedDirectory"]
    beds = [bed for bed, meta in directory.items() if meta["buildingId"] == annex and meta["floorNumber"] == 1]
    for bed, person in zip(beds, ("r018", "r019"), strict=True):
        command("care.transfer", residentId=person, bedId=bed)
    main = care_areas.read(store, token, facility.MAIN)
    other = care_areas.read(store, token, annex)
    positions = ((54, 9), (8, 9), (54, 55), (8, 55))
    for building in (main, other):
        for floor in building["floors"]:
            rooms = [r for r in building["rooms"] if r["floorId"] == floor["id"]]
            if rooms:
                command("facility.setLayout", floorId=floor["id"], rooms=[
                    dict(roomId=r["id"], x=x, y=y, w=38, h=32)
                    for r, (x, y) in zip(rooms, positions)
                ])

    def area(building, name, parent="", *, floors=(), rooms=()):
        command("care.areaSave", buildingId=building, name=name, parentId=parent,
                floorIds=list(floors), roomIds=list(rooms))
        return next(a["id"] for a in care_areas.read(store, token, building)["areas"]
                    if a["name"] == name and a["parentId"] == parent)

    living = area(facility.MAIN, "生活照护")
    first = area(facility.MAIN, "首层照护", living, floors=("floor-1",))
    near = area(facility.MAIN, "近护理站房间", first, rooms=[
        r["id"] for r in main["rooms"] if r["floorId"] == "floor-1" and r["number"] in ("101", "102")
    ])
    second = area(facility.MAIN, "二层日常照护", living, floors=("floor-2",))
    third = area(facility.MAIN, "三层重点照护", floors=("floor-3",))
    recovery = area(annex, "康复支持")
    therapy = area(annex, "首层康复照护", recovery, floors=(other["floors"][0]["id"],))
    upper = area(annex, "二层训练准备", recovery, floors=(other["floors"][1]["id"],))

    for username, name, role in (
        ("demo-lin", "林晓", "护工"), ("demo-chen", "陈悦", "护工"),
        ("demo-zhou", "周宁", "护士长"), ("demo-wu", "吴桐", "护工"),
    ):
        command("access.create", username=username, kind="staff", displayName=name, role=role,
                campusId=facility.HOME_CAMPUS, password=secrets.token_urlsafe(24))
    people = {row["username"]: row["id"] for row in store.snapshot(token)["data"]["accounts"]}
    for building, username, areas in (
        (facility.MAIN, "demo-lin", (near, second)), (facility.MAIN, "demo-chen", (first, third)),
        (facility.MAIN, "demo-zhou", (living, third)), (annex, "demo-lin", (therapy,)),
        (annex, "demo-wu", (therapy, upper)),
    ):
        command("care.areaAssign", buildingId=building, staffId=people[username], areaIds=list(areas))


def schedules(store, token, command):
    now = store.now()
    day = now.date().isoformat()
    people = sorted(row["id"] for row in scheduled_work.read(store, token)["roster"])
    dispatch = (
        ("早间巡查", "07:00", ""), ("每日早餐", "07:30", "早餐"), ("每日午餐", "12:00", "午餐"),
        ("每日晚餐", "18:00", "晚餐"), ("晚间巡查", "20:00", ""),
    )
    rules = {}
    for title, hour, meal in dispatch:
        title = "Demo · " + title
        menu = [entry.split() for entry in WEEKLY[meal]] if meal else []
        fields = dict(
            title=title, kind="meal" if meal else "patrol", weekdays=list(range(1, 8)),
            scope={"kind": "residents", "residentIds": people},
            startDate=day, endDate="", mealKind=meal, menu=menu[0] if menu else [],
            enabled=True, note="核对实际用餐并记录例外。" if meal else "巡视长者，登记需要跟进的事项。",
        )
        if menu:
            fields["weeklyMenus"] = {str(i): value for i, value in enumerate(menu, 1)}
        command("care.saveSchedule", **fields, time=now.strftime("%H:%M"))
        rules[title] = dict(fields, time=hour)
    scheduled_work.tick(store)
    for row in scheduled_work.read(store, token)["rules"]:
        if row["title"] in rules:
            command("care.saveSchedule", **rules[row["title"]], id=row["id"])


def main():
    parser = argparse.ArgumentParser(description="建立安康家园新版演示库")
    parser.add_argument("--db", required=True, type=Path)
    args = parser.parse_args()
    if args.db.exists():
        parser.error("请选择一个尚未创建的数据库文件")
    password = os.environ.get("NH_OWNER_PASSWORD") or getpass("设置新演示库 Owner 口令：")
    store = Store(args.db, initial_data="demo", initial_owner_password=password)
    token, _ = store.login("owner", password)

    def command(action, **fields):
        return store.execute(action, fields, store.version(token)["revision"], token)

    try:
        structure(store, token, command)
        schedules(store, token, command)
    finally:
        store.logout(token)
    print(f"新版演示库已创建：{args.db}")


if __name__ == "__main__":
    main()
