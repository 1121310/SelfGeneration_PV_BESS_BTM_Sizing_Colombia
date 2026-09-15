#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Utilidades comunes de preparacion de datos para el modelo de
dimensionamiento optimo PV+BESS BtM adaptado a Colombia (Proyecto 2).

Fuentes y supuestos regulatorios (documentados en el informe tecnico):
 - Precio de bolsa nacional horario 2005-2023 (COP/kWh, precios constantes),
   archivo PreciosBolsa_2005_2023.xlsx (fuente: XM).
 - Tarifa N2 (T+D+Pr+R+Cv): se aproxima como
   psi_N2 = CU_N2_industrial_promedio - G_promedio, usando referencias
   publicas de Superservicios (Boletin tarifario I trim. 2024, SUI):
     CU_N2_industrial ~ 560 COP/kWh (Antioquia/Centro/Occidente, ind.)
     G (componente de generacion, Grupo 1 comercializadores) ~ 335 COP/kWh
   => psi_N2 ~ 225 COP/kWh (constante, igual simplificacion que el psi.inc
   original del modelo espanol, que tambien es plano).
 - TRM de referencia: 3,915.0 COP/USD (promedio Bance de la Republica,
   1T-2024, publicado por Superservicios en el mismo boletin).
 - Cargo fijo de respaldo CREG (AGGE, Res. CREG 015/2018 via Res. 174/2021):
   CRESP en N2 ~ 2,800 COP/kW-mes (promedio Codensa/EPM/Electricaribe,
   escenario h=1 hora, el mas razonable segun el estudio SER Colombia
   "Propuesta de revision del costo de respaldo para autogeneradores",
   2020, que aplica la metodologia oficial CREG 015/2018).
 - Frontera de conexion: se interpreta como el limite fisico de
   importacion/exportacion igual a la carga instalada (PmaxF = Plinst),
   igual que en la version original del repositorio (RioHacha300kW);
   el valor "1000 MW" del enunciado excede holgadamente cualquier AGGE
   de 1 MW y por tanto no es una restriccion activa.
 - No se incluyen cargos de potencia horarios (kappa = 0 en las 6 franjas).
"""
import os
import re
import numpy as np
import pandas as pd
import openpyxl

HERE = os.path.dirname(__file__)
PROJ = os.path.join(HERE, "..")
REPO = os.path.join(PROJ, "repo_extracted", "SelfGeneration_PV_BESS_BTM_Sizing-main")
PV_RAW = os.path.join(HERE, "pv_raw")
CACHE = os.path.join(HERE, "cache")
os.makedirs(CACHE, exist_ok=True)

YEARS = list(range(2005, 2024))  # 19 años
HOURS_YEAR = 8760

# ---------------------------------------------------------------------
# Constantes regulatorias / de mercado colombianas
# ---------------------------------------------------------------------
TRM = 3915.0                 # COP/USD (Superservicios, 1T-2024)
PSI_N2_COP_KWH = 225.0        # T+D+Pr+R+Cv, N2 industrial (representativo)
PSI_N2_USD_KWH = PSI_N2_COP_KWH / TRM
CRESP_COP_KW_MES = 2800.0     # cargo de respaldo N2, h=1 (SER Colombia / CREG 015-2018)
CRESP_COP_KW_ANIO = CRESP_COP_KW_MES * 12.0

# Factor de correccion climatica Version B (RCP8.5, 2070-2099 vs 1970-1999)
# segun Narvaez et al. 2023 (Environ. Res. Commun. 5 081004), zonificacion
# cualitativa de Colombia (ver Fig. 1d y discusion por region):
CLIMATE_FACTOR = {
    (-4.206, -69.943): 1.05,   # Amazonas (Leticia) - sureste, aumento irradiancia
    (10.469, -73.322): 1.04,   # Cesar/Guajira interior - norte
    (10.953, -74.834): 1.04,   # Atlantico (Barranquilla) - norte/caribe
    (11.539, -72.907): 1.05,   # Guajira - extremo norte
    (12.018, -71.766): 1.05,   # Guajira (Nazareth) - extremo norte
    (2.926, -75.286):  0.985,  # Huila (Neiva) - suroccidente
    (3.451, -76.538):  0.985,  # Valle del Cauca (Cali) - suroccidente
    (4.615, -74.113):  1.015,  # Bogota - centro andino, promedio nacional
    (5.702, -76.662):  0.99,   # Choco (Pacifico) - costa oeste
    (6.187, -67.488):  1.05,   # Vichada - Orinoquia, aumento irradiancia
    (6.207, -75.625):  1.04,   # Antioquia (Medellin) - noroccidente
    (7.110, -73.155):  1.03,   # Santander (Bucaramanga) - norte-centro
}

FNAME_RE = re.compile(
    r"Timeseries_(?P<lat>-?\d+\.\d+)_(?P<lon>-?\d+\.\d+)_E5_1kWp_crystSi_"
    r"(?P<loss>\d+)_(?P<tilt>-?\d+)deg_(?P<az>-?\d+)deg_(?P<y0>\d+)_(?P<y1>\d+)\.csv"
)

NODE_NAMES = {
    (-4.206, -69.943): "Leticia (Amazonas)",
    (10.469, -73.322): "Valledupar (Cesar)",
    (10.953, -74.834): "Barranquilla (Atlantico)",
    (11.539, -72.907): "Riohacha interior (Guajira)",
    (12.018, -71.766): "Nazareth (Alta Guajira)",
    (2.926, -75.286):  "Neiva (Huila)",
    (3.451, -76.538):  "Cali (Valle del Cauca)",
    (4.615, -74.113):  "Bogota D.C.",
    (5.702, -76.662):  "Nuqui (Choco)",
    (6.187, -67.488):  "Puerto Carreno (Vichada)",
    (6.207, -75.625):  "Medellin (Antioquia)",
    (7.110, -73.155):  "Bucaramanga (Santander)",
}


def list_nodes():
    """Devuelve lista de dicts con metadatos de los 12 nodos (desde el
    directorio raiz del proyecto, archivos Timeseries_*.csv originales)."""
    nodes = []
    for f in sorted(os.listdir(PROJ)):
        m = FNAME_RE.match(f)
        if m:
            d = m.groupdict()
            lat, lon = float(d["lat"]), float(d["lon"])
            nodes.append({
                "lat": lat, "lon": lon,
                "tilt": int(d["tilt"]), "az": int(d["az"]),
                "orig_file": os.path.join(PROJ, f),
                "name": NODE_NAMES.get((lat, lon), f"{lat},{lon}"),
                "climate_factor": CLIMATE_FACTOR.get((lat, lon), 1.0),
            })
    return nodes


def _parse_pvgis_csv(path):
    """Lee un CSV crudo de PVGIS seriescalc y devuelve DataFrame con
    columnas time(datetime UTC), P (W por kWp instalado)."""
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        lines = f.readlines()
    start = next(i for i, l in enumerate(lines) if l.startswith("time,"))
    end = next((i for i in range(start + 1, len(lines)) if not lines[i][:1].isdigit()), len(lines))
    from io import StringIO
    chunk = "".join(lines[start:end])
    df = pd.read_csv(StringIO(chunk))
    df["time"] = pd.to_datetime(df["time"], format="%Y%m%d:%H%M")
    return df[["time", "P"]]


def load_node_ppvu(node, use_cache=True):
    """Devuelve un array numpy (19*8760,) con el factor de planta Ppvu
    (p.u., 0-1 aprox) en hora local Colombia (UTC-5), alineado
    exactamente a 8760 horas/anio (se descartan 29-feb, igual que PVGIS).
    Concatena 2005..2023 en orden cronologico ("Version A", 19*8760h)."""
    lat, lon = node["lat"], node["lon"]
    cache_path = os.path.join(CACHE, f"ppvu_{lat}_{lon}.npy")
    if use_cache and os.path.exists(cache_path):
        return np.load(cache_path)

    # localizar archivo fuente: el original de 1 anio, o el descargado 2005-2023
    downloaded = os.path.join(
        PV_RAW, f"PVGIS_{lat}_{lon}_tilt{node['tilt']}_az{node['az']}_2005_2023.csv")
    src = downloaded if os.path.exists(downloaded) else node["orig_file"]
    df = _parse_pvgis_csv(src)

    # hora local Colombia = UTC-5
    df["time_local"] = df["time"] - pd.Timedelta(hours=5)
    df = df.drop_duplicates(subset="time_local").set_index("time_local").sort_index()

    out = np.zeros(len(YEARS) * HOURS_YEAR)
    for yi, y in enumerate(YEARS):
        yr = df[(df.index.year == y) & ~((df.index.month == 2) & (df.index.day == 29))]
        if len(yr) >= HOURS_YEAR:
            vals = yr["P"].to_numpy()[:HOURS_YEAR]
        else:
            # anio no disponible (nodos que solo tienen 2005): reusar 2005
            yr0 = df[(df.index.year == 2005) & ~((df.index.month == 2) & (df.index.day == 29))]
            vals = yr0["P"].to_numpy()[:HOURS_YEAR]
            if len(vals) < HOURS_YEAR:
                vals = np.pad(vals, (0, HOURS_YEAR - len(vals)))
        out[yi * HOURS_YEAR:(yi + 1) * HOURS_YEAR] = vals / 1000.0  # W/kWp -> p.u. (kW/kWp)

    np.save(cache_path, out)
    return out


def load_bolsa_hourly():
    """Lee PreciosBolsa_2005_2023.xlsx y devuelve array (19*8760,) COP/kWh
    en orden cronologico 2005-01-01 hora1 ... 2023-12-31 hora24, sin 29-feb."""
    cache_path = os.path.join(CACHE, "bolsa_hourly.npy")
    if os.path.exists(cache_path):
        return np.load(cache_path)
    xlsx = os.path.join(PROJ, "PreciosBolsa_2005_2023.xlsx")
    wb = openpyxl.load_workbook(xlsx, data_only=True)
    ws = wb.active
    dates = [ws.cell(row=1, column=c).value for c in range(2, ws.max_column + 1)]
    hourly = np.array([[ws.cell(row=r, column=c).value for c in range(2, ws.max_column + 1)]
                        for r in range(3, 27)], dtype=float)  # 24 x ndays
    df = pd.DataFrame(hourly.T, index=pd.to_datetime(dates),
                       columns=[f"P{h}" for h in range(1, 25)])
    df = df[~((df.index.month == 2) & (df.index.day == 29))]
    out = np.zeros(len(YEARS) * HOURS_YEAR)
    for yi, y in enumerate(YEARS):
        yr = df[df.index.year == y].sort_index()
        vals = yr.to_numpy().flatten()  # 365 dias x 24h en orden hora-dentro-de-dia
        if len(vals) != HOURS_YEAR:
            vals = np.resize(vals, HOURS_YEAR)
        out[yi * HOURS_YEAR:(yi + 1) * HOURS_YEAR] = vals
    np.save(cache_path, out)
    return out


def read_inc(path):
    values = {}
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            if not line.lstrip().startswith("t"):
                continue
            parts = re.split(r"\s+", line.strip())
            if len(parts) >= 2:
                try:
                    hour = int(parts[0][1:])
                    value = float(parts[1])
                    values[hour] = value
                except ValueError:
                    continue
    return values


def load_demand_curve(name):
    """name in {'Plu','Plu2','PluDataCenter'} -> array (19*8760,) factor
    de carga p.u. (perfil unico de un anio tipico, replicado 19 veces)."""
    fname = {"Plu": "Plu.inc", "Plu2": "Plu2.inc", "PluDataCenter": "PluDataCenter.inc"}[name]
    vals = read_inc(os.path.join(REPO, fname))
    year = np.array([vals.get(t, 0.0) for t in range(1, HOURS_YEAR + 1)])
    return np.tile(year, len(YEARS))


if __name__ == "__main__":
    nodes = list_nodes()
    print(f"{len(nodes)} nodos encontrados")
    bolsa = load_bolsa_hourly()
    print("Bolsa: n=", len(bolsa), "mean=", bolsa.mean(), "min=", bolsa.min(), "max=", bolsa.max())
    for name in ["Plu", "Plu2", "PluDataCenter"]:
        d = load_demand_curve(name)
        print(name, "n=", len(d), "mean=", d.mean())
