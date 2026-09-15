#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Analisis, verificacion y generacion de mapas/tablas a partir de
results.csv (72 corridas: 12 nodos x 3 curvas de demanda x 2 versiones).
Genera:
 - figs/*.png  (mapas LCOE y comparativos)
 - tables/*.tex (tablas LaTeX listas para incluir en el informe)
 - checks.txt  (verificacion de consistencia / rango regulatorio)
"""
import os
import json
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import Normalize
import matplotlib.cm as cm

HERE = os.path.dirname(__file__)
FIGS = os.path.join(HERE, "figs")
TABLES = os.path.join(HERE, "tables")
os.makedirs(FIGS, exist_ok=True)
os.makedirs(TABLES, exist_ok=True)

df = pd.read_csv(os.path.join(HERE, "results.csv"))
df["ok"] = df["ok"].astype(str) == "True"

DEMAND_LABEL = {"Plu": "Industria 1", "Plu2": "Industria 2", "PluDataCenter": "Centro de datos"}
df["demand_label"] = df["demand_curve"].map(DEMAND_LABEL)

with open(os.path.join(HERE, "colombia.geojson"), encoding="utf-8") as f:
    geo = json.load(f)
coords = geo["features"][0]["geometry"]["coordinates"][0]
col_lon = [c[0] for c in coords]
col_lat = [c[1] for c in coords]

# ---------------------------------------------------------------------
# 1) Verificacion de consistencia
# ---------------------------------------------------------------------
checks = []
checks.append(f"Filas totales: {len(df)} (esperado 72)")
checks.append(f"Filas ok=True: {df['ok'].sum()}")
n_out_of_band = ((df["Ppvinst_kWp"] < 999) | (df["Ppvinst_kWp"] > 5001)).sum()
checks.append(f"Filas con Ppvinst fuera de banda AGGE [1,5] MW: {n_out_of_band}")
checks.append(f"Ppvinst_kWp: min={df['Ppvinst_kWp'].min():.1f} max={df['Ppvinst_kWp'].max():.1f} "
              f"media={df['Ppvinst_kWp'].mean():.1f}")
checks.append(f"C_kWh (BESS): min={df['C_kWh'].min():.1f} max={df['C_kWh'].max():.1f} "
              f"media={df['C_kWh'].mean():.1f}")
checks.append(f"LCOEgross USD/MWh: min={df['LCOEgross_usd_MWh'].min():.1f} "
              f"max={df['LCOEgross_usd_MWh'].max():.1f} media={df['LCOEgross_usd_MWh'].mean():.1f}")
checks.append(f"LCOEnet USD/MWh: min={df['LCOEnet_usd_MWh'].min():.1f} "
              f"max={df['LCOEnet_usd_MWh'].max():.1f} media={df['LCOEnet_usd_MWh'].mean():.1f}")
neg_gross = (df["LCOEgross_usd_MWh"] < 0).sum()
checks.append(f"Filas con LCOEgross negativo (inesperado): {neg_gross}")
n_dup = df.duplicated(subset=["node_name", "demand_curve", "version"]).sum()
checks.append(f"Filas duplicadas (node,demand,version): {n_dup}")
# TIR/BCratio sanity
checks.append(f"TIR%: min={df['TIR_pct'].min():.1f} max={df['TIR_pct'].max():.1f}")
checks.append(f"BCratio: min={df['BCratio'].min():.2f} max={df['BCratio'].max():.2f}")
# Climate effect direction check (B vs A) vs expected climate_factor sign
piv_check = df.pivot_table(index=["node_name", "demand_curve"], columns="version",
                            values="wpvmx_kWh_yr")
delta_gen = (piv_check["B"] - piv_check["A"]) / piv_check["A"]
checks.append(f"Cambio en generacion PV maxima disponible (B vs A): "
              f"min={delta_gen.min()*100:.2f}% max={delta_gen.max()*100:.2f}%")

with open(os.path.join(HERE, "checks.txt"), "w", encoding="utf-8") as f:
    f.write("\n".join(checks))
print("\n".join(checks))

# ---------------------------------------------------------------------
# 2) Tablas resumen (promedio de las 3 curvas de demanda, por nodo)
# ---------------------------------------------------------------------
node_meta = df.drop_duplicates("node_name")[["node_name", "lat", "lon"]].set_index("node_name")

def summary_table(version):
    d = df[df["version"] == version]
    g = d.groupby("node_name").agg(
        lat=("lat", "first"), lon=("lon", "first"),
        Ppvinst_kWp=("Ppvinst_kWp", "mean"), C_kWh=("C_kWh", "mean"),
        LCOEgross=("LCOEgross_usd_MWh", "mean"), LCOEnet=("LCOEnet_usd_MWh", "mean"),
    ).sort_values("LCOEgross")
    return g

tabA = summary_table("A")
tabB = summary_table("B")

def df_to_latex(g, caption, label):
    # table* = ancho completo (2 columnas), necesario en IEEEtran porque
    # una sola columna (~3.5in) es demasiado angosta para 5 campos con
    # nombres de nodo largos (se veia recortada en la compilacion de prueba).
    lines = [
        r"\begin{table*}[htbp]", r"\centering",
        r"\caption{" + caption + "}", r"\label{" + label + "}",
        r"\begin{tabular}{lrrrr}", r"\toprule",
        r"Nodo & PV (kWp) & BESS (kWh) & LCOE$_{gross}$ (USD/MWh) & LCOE$_{net}$ (USD/MWh) \\ \midrule",
    ]
    for name, row in g.iterrows():
        lines.append(f"{name} & {row['Ppvinst_kWp']:.0f} & {row['C_kWh']:.0f} & "
                      f"{row['LCOEgross']:.1f} & {row['LCOEnet']:.1f} \\\\")
    lines += [r"\bottomrule", r"\end{tabular}", r"\end{table*}"]
    return "\n".join(lines)

with open(os.path.join(TABLES, "tabla_version_a.tex"), "w", encoding="utf-8") as f:
    f.write(df_to_latex(tabA, "Resultados Version A (historica 2005-2023), promedio de las 3 curvas de demanda",
                         "tab:versionA"))
with open(os.path.join(TABLES, "tabla_version_b.tex"), "w", encoding="utf-8") as f:
    f.write(df_to_latex(tabB, "Resultados Version B (cambio climatico), promedio de las 3 curvas de demanda",
                         "tab:versionB"))

# Tabla completa (72 filas) por curva de demanda
piv_gross = df.pivot_table(index="node_name", columns=["demand_label", "version"],
                            values="LCOEgross_usd_MWh")
piv_net = df.pivot_table(index="node_name", columns=["demand_label", "version"],
                          values="LCOEnet_usd_MWh")
piv_gross.to_csv(os.path.join(TABLES, "matriz_LCOEgross.csv"))
piv_net.to_csv(os.path.join(TABLES, "matriz_LCOEnet.csv"))

# Impacto climatico (Version B vs A), promedio de las 3 curvas
imp = df.pivot_table(index="node_name", columns="version",
                      values=["LCOEgross_usd_MWh", "LCOEnet_usd_MWh", "Ppvinst_kWp", "C_kWh"])
delta_lcoe_gross = (imp[("LCOEgross_usd_MWh", "B")] - imp[("LCOEgross_usd_MWh", "A")])
delta_pct = 100 * delta_lcoe_gross / imp[("LCOEgross_usd_MWh", "A")]
climate_tab = pd.DataFrame({
    "LCOEgross_A": imp[("LCOEgross_usd_MWh", "A")],
    "LCOEgross_B": imp[("LCOEgross_usd_MWh", "B")],
    "Delta_USD_MWh": delta_lcoe_gross,
    "Delta_pct": delta_pct,
}).sort_values("Delta_pct")
climate_tab.to_csv(os.path.join(TABLES, "impacto_climatico.csv"))

lines = [
    r"\begin{table}[htbp]", r"\centering",
    r"\caption{Impacto del cambio climatico en el LCOE$_{gross}$ (Version B vs A), promedio de las 3 curvas de demanda}",
    r"\label{tab:climate}",
    r"\small",
    r"\begin{tabular}{lrrr}", r"\toprule",
    r"Nodo & LCOE$_{gross}$ A & LCOE$_{gross}$ B & $\Delta$ \\",
    r" & (USD/MWh) & (USD/MWh) & (\%) \\ \midrule",
]
for name, row in climate_tab.iterrows():
    short = name.split(" (")[0]
    lines.append(f"{short} & {row['LCOEgross_A']:.1f} & {row['LCOEgross_B']:.1f} & "
                  f"{row['Delta_pct']:+.1f} \\\\")
lines += [r"\bottomrule", r"\end{tabular}", r"\end{table}"]
with open(os.path.join(TABLES, "tabla_impacto_climatico.tex"), "w", encoding="utf-8") as f:
    f.write("\n".join(lines))

# ---------------------------------------------------------------------
# 3) Mapas
# ---------------------------------------------------------------------
def plot_map(values_by_node, title, fname, cmap="viridis_r", unit="USD/MWh"):
    fig, ax = plt.subplots(figsize=(6, 7))
    ax.plot(col_lon, col_lat, color="0.3", linewidth=1)
    ax.fill(col_lon, col_lat, color="0.94", zorder=0)
    lats = node_meta["lat"].values
    lons = node_meta["lon"].values
    vals = np.array([values_by_node[n] for n in node_meta.index])
    norm = Normalize(vmin=vals.min(), vmax=vals.max())
    sc = ax.scatter(lons, lats, c=vals, cmap=cmap, norm=norm, s=160,
                     edgecolors="k", linewidths=0.6, zorder=3)
    SHORT = {"Riohacha interior (Guajira)": "Riohacha int.",
              "Nazareth (Alta Guajira)": "Nazareth",
              "Puerto Carreno (Vichada)": "P. Carreno"}
    for n, lo, la in zip(node_meta.index, lons, lats):
        short = SHORT.get(n, n.split(" (")[0])
        dy = -9 if n == "Nazareth (Alta Guajira)" else 4
        ax.annotate(short, (lo, la), textcoords="offset points", xytext=(6, dy), fontsize=6.5)
    ax.set_xlim(-80, -64.5)
    ax.set_ylim(-5, 13.5)
    ax.set_xlabel("Longitud")
    ax.set_ylabel("Latitud")
    ax.set_title(title, fontsize=11)
    ax.set_aspect("equal")
    cb = fig.colorbar(sc, ax=ax, shrink=0.7)
    cb.set_label(unit)
    fig.tight_layout()
    fig.savefig(os.path.join(FIGS, fname), dpi=200)
    plt.close(fig)


def node_values(version, metric, demand=None):
    d = df[df["version"] == version]
    if demand:
        d = d[d["demand_curve"] == demand]
        g = d.set_index("node_name")[metric]
    else:
        g = d.groupby("node_name")[metric].mean()
    return g.to_dict()

plot_map(node_values("A", "LCOEgross_usd_MWh"),
          "LCOE gross - Version A (historica 2005-2023)\npromedio 3 curvas de demanda",
          "mapa_LCOEgross_A.png")
plot_map(node_values("A", "LCOEnet_usd_MWh"),
          "LCOE net - Version A (historica 2005-2023)\npromedio 3 curvas de demanda",
          "mapa_LCOEnet_A.png", cmap="RdYlGn_r")
plot_map(node_values("B", "LCOEgross_usd_MWh"),
          "LCOE gross - Version B (cambio climatico RCP8.5, fin de siglo)\npromedio 3 curvas de demanda",
          "mapa_LCOEgross_B.png")
plot_map(node_values("B", "LCOEnet_usd_MWh"),
          "LCOE net - Version B (cambio climatico RCP8.5, fin de siglo)\npromedio 3 curvas de demanda",
          "mapa_LCOEnet_B.png", cmap="RdYlGn_r")

delta_dict = climate_tab["Delta_pct"].to_dict()
plot_map(delta_dict, "Variacion del LCOE gross por cambio climatico\n(Version B vs A, %)",
          "mapa_delta_climatico.png", cmap="RdBu_r", unit="% cambio LCOEgross")

# ---------------------------------------------------------------------
# 4) Grafico de barras: LCOEgross vs LCOEnet por nodo (Version A, DataCenter)
# ---------------------------------------------------------------------
dA = df[(df["version"] == "A") & (df["demand_curve"] == "PluDataCenter")].sort_values("LCOEgross_usd_MWh")
fig, ax = plt.subplots(figsize=(8, 5))
x = np.arange(len(dA))
w = 0.35
ax.bar(x - w/2, dA["LCOEgross_usd_MWh"], w, label="LCOE gross")
ax.bar(x + w/2, dA["LCOEnet_usd_MWh"], w, label="LCOE net")
ax.axhline(0, color="k", linewidth=0.7)
ax.set_xticks(x)
ax.set_xticklabels([n.split(" (")[0] for n in dA["node_name"]], rotation=45, ha="right", fontsize=8)
ax.set_ylabel("USD/MWh")
ax.set_title("LCOE gross vs. LCOE net por nodo\n(Version A, curva Centro de Datos)")
ax.legend()
fig.tight_layout()
fig.savefig(os.path.join(FIGS, "barras_gross_vs_net.png"), dpi=200)
plt.close(fig)

print("\nListo: figs/ y tables/ generados.")
