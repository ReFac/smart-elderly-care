"""Generate offline address choices from the documented pinned modood/dist CSV files."""

import argparse
import csv
import json
from pathlib import Path

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument(
    "source",
    type=Path,
    help="contains provinces.csv through villages.csv and HK-MO-TW.json",
)
parser.add_argument("destination", type=Path)
args = parser.parse_args()

tree = {}
cities = {}
for table, parent in (
    ("provinces", None),
    ("cities", "provinceCode"),
    ("areas", "cityCode"),
    ("streets", "areaCode"),
    ("villages", "streetCode"),
):
    with (args.source / (table + ".csv")).open(encoding="utf-8-sig", newline="") as src:
        for row in csv.DictReader(src):
            if table == "streets" and row["provinceCode"] != "41":
                continue
            if table == "villages" and row["provinceCode"] != "41":
                continue
            key, name = row["code"], row["name"]
            up = row[parent] if parent else "CN"
            # Source IDs stay stable across renames/moves. They are internal lookup keys.
            if key == "410482207":
                name = "骑岭街道"
            if key == "410482108220":
                up = "410482207"
            dest = (
                cities.setdefault(row["cityCode"], {})
                if table == "villages" and row["cityCode"] != "4104"
                else tree
            )
            dest.setdefault(up, {})[key] = name

special = json.loads((args.source / "HK-MO-TW.json").read_text())
for name, code in (
    ("香港特别行政区", "81"),
    ("澳门特别行政区", "82"),
    ("台湾省", "71"),
):
    tree["CN"][code] = name
    for ci, (city, districts) in enumerate(special[name].items(), 1):
        city_id = f"{code}-c{ci}"
        tree.setdefault(code, {})[city_id] = city
        tree[city_id] = {f"{city_id}-d{i}": d for i, d in enumerate(districts, 1)}


def write(destination, data):
    with destination.open("w", encoding="utf-8") as out:
        out.write("{\n")
        out.write(
            ",\n".join(
                json.dumps(key)
                + ":"
                + json.dumps(options, ensure_ascii=False, separators=(",", ":"))
                for key, options in data.items()
            )
        )
        out.write("\n}\n")


write(args.destination, tree)
folder = args.destination.parent / "henan-villages"
folder.mkdir(exist_ok=True)
for code, data in cities.items():
    write(folder / (code + ".json"), data)
