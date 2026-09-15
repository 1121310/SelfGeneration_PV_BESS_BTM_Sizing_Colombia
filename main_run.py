#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Orquestador principal: corre el modelo PV+BESS BtM adaptado a Colombia
para las 12 ubicaciones x 3 curvas de demanda x 2 versiones (A: historica
2005-2023, B: correccion por cambio climatico), y guarda resultados en
results.csv de forma incremental (append), para poder retomar si se
interrumpe.
"""
import os
import sys
import time
import csv

sys.path.insert(0, os.path.dirname(__file__))
from prep_common import (list_nodes, load_node_ppvu, load_bolsa_hourly,
                          load_demand_curve, PSI_N2_USD_KWH, TRM, CRESP_COP_KW_ANIO)
from pv_bess_colombia import solve_case

HERE = os.path.dirname(__file__)
OUT_CSV = os.path.join(HERE, "results.csv")

PLINST = 1000.0  # kW, carga de 1 MW (las 3 curvas)
CRESP_USD_YEAR = CRESP_COP_KW_ANIO * PLINST / TRM

FIELDS = [
    "node_name", "lat", "lon", "demand_curve", "version", "climate_factor",
    "ok", "C_kWh", "PinverterBESS_kW", "Ppvinst_kWp", "PinverterPV_kW", "ILR", "Npan",
    "Wl_kWh_yr", "Wb_kWh_yr", "Ws_kWh_yr", "Wc_kWh_yr", "Wd_kWh_yr",
    "wpvmx_kWh_yr", "wpv_kWh_yr", "wclipping_kWh_yr",
    "Benefit_usd_yr", "OPEX_usd_yr", "OPEX0_usd_yr", "Savings_usd_yr",
    "Eb_usd_yr", "Eb0_usd_yr", "Es_usd_yr", "CAPEX_usd", "NPV_usd",
    "CashFlow_usd_yr", "TIR_pct", "BCratio", "LCOEnet_usd_MWh", "LCOEgross_usd_MWh",
    "n_years", "solve_time_s",
]

DEMAND_CURVES = ["Plu", "Plu2", "PluDataCenter"]
VERSIONS = ["A", "B"]


def already_done():
    done = set()
    if os.path.exists(OUT_CSV):
        with open(OUT_CSV, "r", newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                done.add((row["node_name"], row["demand_curve"], row["version"]))
    return done


def main():
    nodes = list_nodes()
    bolsa_cop = load_bolsa_hourly()
    lambda_usd = bolsa_cop / TRM
    psi_usd = (lambda_usd * 0.0) + PSI_N2_USD_KWH

    write_header = not os.path.exists(OUT_CSV)
    done = already_done()
    print(f"Ya completados: {len(done)}", flush=True)

    with open(OUT_CSV, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        if write_header:
            writer.writeheader()
            f.flush()

        total = len(nodes) * len(DEMAND_CURVES) * len(VERSIONS)
        k = 0
        for node in nodes:
            ppvu_hist = load_node_ppvu(node)
            ppvu_future = ppvu_hist * node["climate_factor"]
            for demand_name in DEMAND_CURVES:
                plu = load_demand_curve(demand_name)
                for version in VERSIONS:
                    k += 1
                    key = (node["name"], demand_name, version)
                    if key in done:
                        print(f"[{k}/{total}] SKIP (ya hecho) {key}", flush=True)
                        continue
                    ppvu = ppvu_hist if version == "A" else ppvu_future
                    t0 = time.time()
                    print(f"[{k}/{total}] Resolviendo {key} ...", flush=True)
                    try:
                        r = solve_case(ppvu, plu, lambda_usd, psi_usd,
                                        Plinst=PLINST, CRESP_usd_year=CRESP_USD_YEAR)
                    except Exception as e:
                        print(f"  ERROR: {e}", flush=True)
                        r = {"ok": False}
                    dt = time.time() - t0
                    row = {
                        "node_name": node["name"], "lat": node["lat"], "lon": node["lon"],
                        "demand_curve": demand_name, "version": version,
                        "climate_factor": node["climate_factor"], "solve_time_s": round(dt, 1),
                    }
                    row.update({kk: r.get(kk) for kk in FIELDS if kk in r})
                    row["ok"] = r.get("ok", False)
                    writer.writerow(row)
                    f.flush()
                    print(f"  -> ok={row['ok']} LCOEnet={row.get('LCOEnet_usd_MWh')} "
                          f"LCOEgross={row.get('LCOEgross_usd_MWh')} t={dt:.1f}s", flush=True)

    print("TODO LISTO.", flush=True)


if __name__ == "__main__":
    main()
