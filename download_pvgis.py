#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Descarga series horarias PVGIS-ERA5 2005-2023 para los nodos colombianos
que en el directorio local solo cuentan con el ano 2005 (archivos de
ejemplo/plantilla). Replica exactamente lat/lon/tilt/azimuth/loss
embebidos en el nombre de archivo original para mantener consistencia
metodologica con el unico nodo que si trae la serie completa
(6.207_-75.625, Medellin).
"""
import os
import re
import time
import urllib.request
import urllib.parse

RAW_DIR = os.path.join(os.path.dirname(__file__), "..")
OUT_DIR = os.path.join(os.path.dirname(__file__), "pv_raw")
os.makedirs(OUT_DIR, exist_ok=True)

API = "https://re.jrc.ec.europa.eu/api/v5_3/seriescalc"

FNAME_RE = re.compile(
    r"Timeseries_(?P<lat>-?\d+\.\d+)_(?P<lon>-?\d+\.\d+)_E5_1kWp_crystSi_"
    r"(?P<loss>\d+)_(?P<tilt>-?\d+)deg_(?P<az>-?\d+)deg_(?P<y0>\d+)_(?P<y1>\d+)\.csv"
)

def find_nodes():
    nodes = []
    for f in os.listdir(RAW_DIR):
        m = FNAME_RE.match(f)
        if m:
            d = m.groupdict()
            d["fname"] = f
            d["years"] = int(d["y1"]) - int(d["y0"]) + 1
            nodes.append(d)
    return nodes

def download_node(lat, lon, tilt, az, loss, out_path, startyear=2005, endyear=2023, retries=3):
    params = {
        "lat": lat, "lon": lon, "raddatabase": "PVGIS-ERA5",
        "startyear": startyear, "endyear": endyear,
        "pvcalculation": 1, "peakpower": 1, "loss": loss,
        "angle": tilt, "aspect": az, "mountingplace": "free",
        "outputformat": "csv",
    }
    url = API + "?" + urllib.parse.urlencode(params)
    for attempt in range(1, retries + 1):
        try:
            t0 = time.time()
            with urllib.request.urlopen(url, timeout=300) as resp:
                data = resp.read()
            with open(out_path, "wb") as f:
                f.write(data)
            dt = time.time() - t0
            print(f"  OK lat={lat} lon={lon} tilt={tilt} az={az} "
                  f"-> {out_path} ({len(data)/1e6:.2f} MB, {dt:.1f}s)")
            return True
        except Exception as e:
            print(f"  ERROR attempt {attempt}/{retries} lat={lat} lon={lon}: {e}")
            time.sleep(5)
    return False

if __name__ == "__main__":
    nodes = find_nodes()
    print(f"Nodos detectados: {len(nodes)}")
    for n in nodes:
        print(" ", n["fname"], "-> years available:", n["years"])
    todo = [n for n in nodes if n["years"] < 15]
    print(f"\nNodos a re-descargar 2005-2023 (17-19 anios): {len(todo)}")
    for n in todo:
        out_name = f"PVGIS_{n['lat']}_{n['lon']}_tilt{n['tilt']}_az{n['az']}_2005_2023.csv"
        out_path = os.path.join(OUT_DIR, out_name)
        if os.path.exists(out_path) and os.path.getsize(out_path) > 2_000_000:
            print(f"  ya existe {out_name}, se omite")
            continue
        print(f"Descargando {n['fname']} ...")
        download_node(n["lat"], n["lon"], n["tilt"], n["az"], n["loss"], out_path)
    print("\nListo.")
