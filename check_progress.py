import os
import csv

OUT_CSV = os.path.join(os.path.dirname(__file__), "results.csv")
if not os.path.exists(OUT_CSV):
    print("Aun no hay resultados.")
else:
    with open(OUT_CSV, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    print(f"Filas completadas: {len(rows)} / 72")
    ok = sum(1 for r in rows if r["ok"] == "True")
    print(f"OK: {ok}, fallidas: {len(rows) - ok}")
    for r in rows[-5:]:
        print(" ", r["node_name"], r["demand_curve"], r["version"],
              "LCOEnet=", r.get("LCOEnet_usd_MWh"), "LCOEgross=", r.get("LCOEgross_usd_MWh"))
