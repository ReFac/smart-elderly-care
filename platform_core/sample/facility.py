"""Configure the two-building training site and daily meal and patrol schedules."""

from platform_core import care_areas, facility, scheduled_work
import secrets


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
    buildings = care_areas.read(store, token)["buildings"]
    def home_annex(rows):
        return next((b["id"] for b in rows if b["name"] == "康复楼" and b["campusId"] == facility.HOME_CAMPUS), None)

    annex = home_annex(buildings)
    if not annex:
        command("facility.addBuilding", name="康复楼", campusId=facility.HOME_CAMPUS)
        annex = home_annex(care_areas.read(store, token)["buildings"])
    floor_numbers = {f["number"] for f in care_areas.read(store, token, annex)["floors"]}
    for number in (1, 2):
        if number not in floor_numbers:
            command("facility.addFloor", buildingId=annex, number=number)
    site = care_areas.read(store, token, annex)
    for floor in site["floors"]:
        number = floor["number"]
        if number in (1, 2) and not any(r["floorId"] == floor["id"] and r["number"] == f"{number}01" for r in site["rooms"]):
            command("facility.addRoom", floorId=floor["id"], number=f"{number}01",
                    ward=f"康复楼 {number} 层", bedCount=2, dailyRate=68)
    data = store.snapshot(token)["data"]
    directory = data["bedDirectory"]
    beds = [b for b in data["beds"] if directory.get(b["id"], {}).get("buildingId") == annex and
            directory[b["id"]]["floorNumber"] == 1 and directory[b["id"]]["roomNumber"] == "101"]
    for bed, (rid, name) in zip(beds, (("r018", "冯玉芬"), ("r019", "郑和宜"))):
        person = next((r for r in data["residents"] if r["id"] == rid and r["name"] == name), None)
        if bed["status"] == "空闲" and person and person["status"] == "在住" and not any(
                m["residentId"] == rid and m["kind"] != "入住" for m in data["bedMoves"]):
            command("care.transfer", residentId=rid, bedId=bed["id"])
    main = care_areas.read(store, token, facility.MAIN)
    other = care_areas.read(store, token, annex)
    positions = ((54, 9), (8, 9), (54, 55), (8, 55))
    for building in (main, other):
        for floor in building["floors"]:
            rooms = [r for r in building["rooms"] if r["floorId"] == floor["id"]]
            if rooms and len(rooms) <= len(positions) and not any(
                    m["floorId"] == floor["id"] and m["x"] is not None for m in directory.values()):
                command("facility.setLayout", floorId=floor["id"], rooms=[
                    dict(roomId=r["id"], x=x, y=y, w=38, h=32)
                    for r, (x, y) in zip(rooms, positions)
                ])

    def area(building, name, parent="", *, floors=(), rooms=()):
        site = care_areas.read(store, token, building)
        old = next((a for a in site["areas"] if a["name"] == name and a["parentId"] == parent), None)
        if old:
            return old["id"]
        floors = [f["id"] for f in site["floors"] if f["id"] in floors and not f["areaId"]]
        rooms = [r["id"] for r in site["rooms"] if r["id"] in rooms and not r["areaId"]]
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
    therapy = area(annex, "首层康复照护", recovery, floors=[f["id"] for f in other["floors"] if f["number"] == 1])
    upper = area(annex, "二层训练准备", recovery, floors=[f["id"] for f in other["floors"] if f["number"] == 2])

    for username, name, role in (
        ("demo-lin", "林晓", "护工"), ("demo-chen", "陈悦", "护工"),
        ("demo-zhou", "周宁", "护士长"), ("demo-wu", "吴桐", "护工"),
    ):
        if not any(r["username"] == username for r in data["accounts"]):
            command("access.create", username=username, kind="staff", displayName=name, role=role,
                    campusId=facility.HOME_CAMPUS, password=secrets.token_urlsafe(24))
    people = {row["username"]: row["id"] for row in store.snapshot(token)["data"]["accounts"]}
    for building, username, areas in (
        (facility.MAIN, "demo-lin", (near, second)), (facility.MAIN, "demo-chen", (first, third)),
        (facility.MAIN, "demo-zhou", (living, third)), (annex, "demo-lin", (therapy,)),
        (annex, "demo-wu", (therapy, upper)),
    ):
        selected = next((a for a in care_areas.read(store, token, building)["staff"] if a["id"] == people[username]), None)
        if selected and selected["selectable"] and not selected["areaIds"]:
            command("care.areaAssign", buildingId=building, staffId=people[username], areaIds=list(areas))


def schedules(store, token, command):
    now = store.now()
    day = now.date().isoformat()
    current = scheduled_work.read(store, token)
    people = sorted(row["id"] for row in current["roster"])
    existing = {row["title"]: row for row in current["rules"]}
    dispatch = (
        ("早间巡查", "07:00", ""), ("每日早餐", "07:30", "早餐"), ("每日午餐", "12:00", "午餐"),
        ("每日晚餐", "18:00", "晚餐"), ("晚间巡查", "20:00", ""),
    )
    rules = {}
    for title, hour, meal in dispatch:
        title = "Demo · " + title
        note = "核对实际用餐并记录例外。" if meal else "巡视长辈，登记需要跟进的事项。"
        initial_note = note + "首次演示派发。"
        previous = existing.get(title)
        if not people or (previous and previous["note"] != initial_note):
            continue
        menu = [entry.split() for entry in WEEKLY[meal]] if meal else []
        fields = dict(
            title=title, kind="meal" if meal else "patrol", weekdays=list(range(1, 8)),
            scope={"kind": "residents", "residentIds": people},
            startDate=previous["startDate"] if previous else day, endDate="", mealKind=meal, menu=menu[0] if menu else [],
            enabled=True, note=note,
        )
        if menu:
            fields["weeklyMenus"] = {str(i): value for i, value in enumerate(menu, 1)}
        if not previous:
            command("care.saveSchedule", **dict(fields, note=initial_note, time=now.strftime("%H:%M")))
        rules[title] = dict(fields, time=hour)
    scheduled_work.tick(store)
    for row in scheduled_work.read(store, token)["rules"]:
        if row["title"] in rules:
            command("care.saveSchedule", **rules[row["title"]], id=row["id"])
