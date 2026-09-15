# Mapas de LCOE óptimo PV+BESS para Colombia (AGGE, CREG 174/2021)

Adaptación del modelo Behind-the-Meter (BtM) de dimensionamiento y despacho óptimo
PV+BESS de [De Oliveira & Salas Durán](https://github.com/pmdeoliveiradejesus/SelfGeneration_PV_BESS_BTM_Sizing)
al marco regulatorio y de mercado colombiano, desarrollado para el Proyecto II del curso
Planeamiento de Sistemas de Potencia (Universidad de los Andes).

Calcula el tamaño óptimo de PV y BESS, y el LCOE bruto/neto, para 12 ubicaciones
colombianas, 3 curvas de demanda de 1 MW y 2 escenarios (histórico 2005-2023 y
corregido por cambio climático RCP8.5), resolviendo 72 optimizaciones de 19 años
(166 440 horas) con Gurobi.

## Estructura del repositorio

```
src/
  prep_common.py        Carga y preparación de datos (PVGIS, precios de bolsa, demanda,
                         constantes regulatorias: TRM, tarifa N2, cargo de respaldo CREG,
                         factores de corrección climática por nodo)
  pv_bess_colombia.py    Modelo de optimización (LP) adaptado a Colombia: solve_case()
  download_pvgis.py      Descarga vía API pública de PVGIS v5.3 las series horarias
                         2005-2023 faltantes para 11 de los 12 nodos
  main_run.py             Orquestador: corre las 72 combinaciones nodo x demanda x versión
                         y escribe resultados.csv de forma incremental (reanudable)
  analyze_results.py      Verificación de consistencia, tablas y mapas de LCOE
  check_progress.py       Utilidad para ver el avance de main_run.py

data/
  colombia.geojson        Contorno del territorio colombiano usado en los mapas

resultados/
  results.csv              Resultado de las 72 optimizaciones (una fila por caso)
  checks.txt                Verificación de consistencia (rangos, banda AGGE, duplicados)
  figs/                    Mapas de LCOE y gráficos comparativos (PNG)
  tables/                  Tablas resumen en LaTeX y CSV
```

Nota: las 12 series horarias PVGIS crudas (~7 MB cada una) y los archivos `.npy` de
caché no se incluyen en este repositorio por tamaño; `download_pvgis.py` y
`prep_common.py` las regeneran automáticamente en la primera ejecución.

## Requisitos

- Python ≥ 3.11
- [Gurobi](https://www.gurobi.com/) con licencia válida (académica gratuita para
  estudiantes/instituciones) y `gurobipy` instalado
- `pip install -r requirements.txt`
- Los archivos fuente originales del proyecto (12 CSV `Timeseries_*.csv` de PVGIS y
  `PreciosBolsa_2005_2023.xlsx`) deben ubicarse en el directorio padre de `src/`
  (mismo nivel que este repositorio), o ajustar las rutas en `prep_common.py`.

## Ejecución

```bash
pip install -r requirements.txt
cd src
python download_pvgis.py      # descarga las 11 series PVGIS faltantes (2005-2023)
python main_run.py            # corre las 72 optimizaciones (~2-4 h; reanudable)
python analyze_results.py     # genera figs/, tables/ y checks.txt
```

## Metodología (resumen)

Ver el informe técnico (`informe/main.pdf`) para el detalle completo. En síntesis:

- **Series de tiempo**: PVGIS-ERA5 (12 nodos, 2005-2023), Precio de Bolsa Nacional
  horario (XM, 2005-2023, precios constantes), tres curvas de demanda de 1 MW
  (`Plu`, `Plu2`, `PluDataCenter`, tomadas del repositorio original).
- **Regulación colombiana incorporada**: tarifa N2 (T+D+Pr+R+Cv, aproximada como
  tarifa plana), cargo fijo de respaldo CREG (CRESP), eliminación de cargos de
  potencia horarios, banda de capacidad AGGE (1-5 MW, Res. CREG 174/2021).
- **Cambio climático (Versión B)**: método *delta-change* con factores de corrección
  por nodo derivados de Narváez et al. (2023), *Environ. Res. Commun.* 5, 081004.
- **Optimización**: LP (variables binarias del modelo original relajadas a continuas,
  validado numéricamente contra el MILP original — ver `pv_bess_colombia.py`).

## Licencia y autoría

Código desarrollado para el Proyecto II (Planeamiento de Sistemas de Potencia,
Universidad de los Andes, 2026) con asistencia de IA (Claude, Anthropic) para la
implementación, depuración y automatización — ver la sección "Uso de Inteligencia
Artificial" del informe técnico para el detalle de alcance y supervisión humana.
