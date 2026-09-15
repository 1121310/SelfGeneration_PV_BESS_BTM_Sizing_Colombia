#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Modelo de dimensionamiento optimo PV+BESS BtM adaptado a Colombia
(AGGE, CREG 174/2021), a partir de PV_BESS_sizing_model.py
(https://github.com/pmdeoliveiradejesus/SelfGeneration_PV_BESS_BTM_Sizing).

Cambios respecto al modelo original (unicamente series de tiempo y
estructura tarifaria, tal como exige el enunciado del Proyecto 2):
 - Horizonte T = 19*8760 horas (2005-2023, Version A) o el mismo largo
   con Ppvu corregido por cambio climatico (Version B, metodo "delta change").
 - lambda = precio de bolsa nacional horario (USD/kWh via TRM), no
   precio spot espanol.
 - psi = tarifa N2 (T+D+Pr+R+Cv), plana y representativa (USD/kWh).
 - Sin cargos de potencia horarios (kappa = 0): se elimina Pbmax/periodo.
 - Cargo fijo anual de respaldo CREG (CRESP) sumado al OPEX con proyecto.
 - Variables binarias w1,w3 (anti carga+descarga y anti compra+venta
   simultaneas) relajadas a continuas: se verifico (test_lp_relax.py)
   que la relajacion LP reproduce exactamente el optimo MILP porque el
   spread comprar>vender y las perdidas de conversion hacen que la
   solucion optima nunca las active simultaneamente.
 - CAPEX/OPEX unitario, tasa de descuento, vida util: SIN CAMBIOS
   respecto al modelo original (Lazard), segun instruccion del
   enunciado ("Solo se deben ajustar las series de tiempo").
 - Capacidad PV nominal restringida a la banda regulatoria AGGE de la
   Res. CREG 174/2021 (1 MW <= Ppvinst <= 5 MW): sin este limite el NPV
   crece de forma monotona con el tamano de planta (arbitraje de bolsa
   vendiendo hasta el limite de frontera 24h/dia via BESS) y el modelo
   converge a una planta "merchant" de decenas de MW, fuera del marco
   normativo de autogeneracion a gran escala que exige el enunciado.
"""
import numpy as np
import numpy_financial as npf
import gurobipy as gp
from gurobipy import GRB, quicksum


def solve_case(Ppvu, Plu, lambda_usd, psi_usd, Plinst=1000.0, CRESP_usd_year=0.0,
                verbose=False, time_limit=None, agge_min_kw=1000.0, agge_max_kw=5000.0):
    T = range(1, len(Ppvu) + 1)
    n_t = len(Ppvu)
    Rmax = 1000.0
    Area = 2.4
    eta = 0.2094
    eff_c = 0.9624
    eff_d = 0.9624
    DoD = 0.90
    PmaxF = Plinst
    BoP = 0.0
    Sc = 1.2
    OaMpv = 12.5
    OaMbess = 5.9
    CAPEX_pv = 388.0
    CAPEX_BESS = 185.0
    CAPEX_inverter = 48.0
    i = 7.7 / 100
    n = 20
    e = 2.5 / 100
    ir = (i - e) / (1 + e)
    crf = (i * (i + 1) ** n) / ((i + 1) ** n - 1)
    crfe = (1 + e) * (ir * (ir + 1) ** n) / ((ir + 1) ** n - 1)

    m = gp.Model('SizingModelColombia')
    m.setParam('OutputFlag', 1 if verbose else 0)
    m.setParam('Method', 2)  # barrier, mejor para LP grande
    m.setParam('Crossover', 0)     # no se requiere base optima exacta
    m.setParam('BarConvTol', 1e-6)  # suficiente para LCOE/NPV de ingenieria
    m.setParam('BarHomogeneous', 1)
    m.setParam('Threads', 6)        # limitar memoria pico del factor de Cholesky
    if time_limit:
        m.setParam('TimeLimit', time_limit)

    Savings = m.addVar(lb=-GRB.INFINITY); OPEX = m.addVar(lb=0)
    npv_var = m.addVar(lb=-GRB.INFINITY); Benefit = m.addVar(lb=-GRB.INFINITY)
    OPEX0 = m.addVar(lb=-GRB.INFINITY); Eb = m.addVar(lb=0); Eb0 = m.addVar(lb=0)
    Es = m.addVar(lb=0); wpvmx = m.addVar(lb=-GRB.INFINITY); wpv = m.addVar(lb=-GRB.INFINITY)
    wclipping = m.addVar(lb=-GRB.INFINITY); Wb = m.addVar(lb=-GRB.INFINITY)
    Ws = m.addVar(lb=-GRB.INFINITY); Wl = m.addVar(lb=-GRB.INFINITY)
    Wd = m.addVar(lb=-GRB.INFINITY); Wc = m.addVar(lb=-GRB.INFINITY)
    CashFlow_var = m.addVar(lb=-GRB.INFINITY); Investment0 = m.addVar(lb=0)
    PinverterBESS = m.addVar(lb=0); PinverterPV = m.addVar(lb=0); Ppvinst = m.addVar(lb=0)
    SOC0 = m.addVar(lb=0); nx = m.addVar(lb=0); C = m.addVar(lb=0)

    SOC = m.addVars(T, lb=0); Ppv = m.addVars(T, lb=0)
    Ppvmx = m.addVars(T, lb=0); Pd = m.addVars(T, lb=0)
    Pc = m.addVars(T, lb=0); Pb = m.addVars(T, lb=0); Ps = m.addVars(T, lb=0)

    data_Plu = {t: float(Plu[t - 1]) for t in T}
    data_Ppvu = {t: float(Ppvu[t - 1]) for t in T}
    data_lambda = {t: float(lambda_usd[t - 1]) for t in T}
    data_psi = {t: float(psi_usd[t - 1]) for t in T}

    for t in T:
        m.addConstr(Pd[t] + Pb[t] + Ppv[t] == Pc[t] + Ps[t] + Plinst * data_Plu[t])
        m.addConstr(Ppvmx[t] == Ppvinst * data_Ppvu[t])
        if t == 1:
            m.addConstr(SOC[t] == SOC0 + Pc[t] * eff_c - Pd[t] / eff_d)
        else:
            m.addConstr(SOC[t] == SOC[t - 1] + Pc[t] * eff_c - Pd[t] / eff_d)
        m.addConstr(Ppv[t] <= Ppvmx[t])
        m.addConstr(Pc[t] <= PinverterBESS)
        m.addConstr(Pd[t] <= PinverterBESS)
        m.addConstr(Pb[t] <= PmaxF)
        m.addConstr(Ps[t] <= PmaxF)
        m.addConstr(SOC[t] <= ((1 - DoD) / 2 + DoD) * C)
        m.addConstr(SOC[t] >= ((1 - DoD) / 2) * C)
    m.addConstr(SOC0 <= ((1 - DoD) / 2 + DoD) * C)
    m.addConstr(SOC0 >= ((1 - DoD) / 2) * C)

    # NOTA: T puede abarcar multiples anios (19*8760 en Version A/B). Todas
    # las sumas horarias se dividen por n_years para obtener flujos ANUALES
    # PROMEDIO (consistentes con crf/crfe, que son factores de anualidad de
    # UN ano tipico proyectado a lo largo de la vida util n del proyecto).
    # Sin esta normalizacion el objetivo trataria el flujo de caja de todo
    # el horizonte historico como si fuera el de un solo anio, sobrestimando
    # el NPV en un factor ~n_years y distorsionando el dimensionamiento.
    n_years_ = n_t / 8760.0
    m.addConstr(Es == quicksum(data_lambda[t] * Ps[t] for t in T) / n_years_)
    m.addConstr(Eb == quicksum((data_lambda[t] + data_psi[t]) * Pb[t] for t in T) / n_years_)
    m.addConstr(Eb0 == quicksum((data_lambda[t] + data_psi[t]) * Plinst * data_Plu[t] for t in T) / n_years_)
    m.addConstr(OPEX0 == Eb0)
    m.addConstr(OPEX == Eb + OaMpv * Ppvinst + OaMbess * C + CRESP_usd_year)
    m.addConstr(Savings == OPEX0 - OPEX)
    m.addConstr(Benefit == Es - OPEX)
    m.addConstr(CashFlow_var == Es + OPEX0 - OPEX)
    m.addConstr(Investment0 == BoP + Sc * (CAPEX_pv * Ppvinst + CAPEX_BESS * C +
                                            CAPEX_inverter * (PinverterBESS + PinverterPV)))
    m.addConstr(npv_var == CashFlow_var / crfe - Investment0)

    m.addConstr(wpv == quicksum(Ppv[t] for t in T) / n_years_)
    m.addConstr(wpvmx == quicksum(Ppvmx[t] for t in T) / n_years_)
    m.addConstr(Wb == quicksum(Pb[t] for t in T) / n_years_)
    m.addConstr(Ws == quicksum(Ps[t] for t in T) / n_years_)
    m.addConstr(Wc == quicksum(Pc[t] for t in T) / n_years_)
    m.addConstr(Wd == quicksum(Pd[t] for t in T) / n_years_)
    m.addConstr(Wl == quicksum(Plinst * data_Plu[t] for t in T) / n_years_)
    m.addConstr(wclipping == wpvmx - wpv)
    m.addConstr(PinverterBESS <= C * 2.0)
    m.addConstr(PinverterBESS >= C * 0.1)
    m.addConstr(nx == 1000 * Ppvinst / (Rmax * eta * Area))
    m.addConstr(PinverterPV == Plinst + PmaxF + PinverterBESS)
    if agge_min_kw is not None:
        m.addConstr(Ppvinst >= agge_min_kw)
    if agge_max_kw is not None:
        m.addConstr(Ppvinst <= agge_max_kw)
    m.setObjective(npv_var, GRB.MAXIMIZE)
    m.optimize()

    if m.Status not in (GRB.OPTIMAL, GRB.SUBOPTIMAL, GRB.TIME_LIMIT):
        status = m.Status
        m.dispose()
        return {"status": status, "ok": False}

    # Es, Eb, Eb0, OPEX, OPEX0, Wb, Ws, Wc, Wd, Wl, wpv, wpvmx ya son
    # promedios ANUALES (normalizados dentro del modelo por n_years_).
    Io = Investment0.X
    CF = CashFlow_var.X  # ya anual
    TIR = npf.irr([-Io] + [CF] * n) * 100 if Io > 0 else 0
    BCratio = npf.pv(rate=i, nper=n, pmt=-CF, fv=0) / Io if Io > 0 else 0
    OPEXgross = OaMpv * Ppvinst.X + OaMbess * C.X
    n_years = n_t / 8760.0
    Wl_annual = Wl.X
    LCOEgross = 1000 * (Io + OPEXgross / crfe) / (Wl_annual / crf) if Wl_annual > 0 else 0
    LCOEnet = 1000 * (Io + (OPEX.X - OPEX0.X - Es.X) / crfe) / (Wl_annual / crf) if Wl_annual > 0 else 0

    result = {
        "ok": True, "status": m.Status,
        "C_kWh": C.X, "PinverterBESS_kW": PinverterBESS.X,
        "Ppvinst_kWp": Ppvinst.X, "PinverterPV_kW": PinverterPV.X,
        "ILR": Ppvinst.X / PinverterPV.X if PinverterPV.X > 0 else 0,
        "Npan": nx.X,
        "Wl_kWh_yr": Wl_annual, "Wb_kWh_yr": Wb.X, "Ws_kWh_yr": Ws.X,
        "Wc_kWh_yr": Wc.X, "Wd_kWh_yr": Wd.X,
        "wpvmx_kWh_yr": wpvmx.X, "wpv_kWh_yr": wpv.X,
        "wclipping_kWh_yr": wclipping.X,
        "Benefit_usd_yr": Benefit.X, "OPEX_usd_yr": OPEX.X,
        "OPEX0_usd_yr": OPEX0.X, "Savings_usd_yr": Savings.X,
        "Eb_usd_yr": Eb.X, "Eb0_usd_yr": Eb0.X, "Es_usd_yr": Es.X,
        "CAPEX_usd": Io, "NPV_usd": npv_var.X, "CashFlow_usd_yr": CF,
        "TIR_pct": TIR, "BCratio": BCratio,
        "LCOEnet_usd_MWh": LCOEnet, "LCOEgross_usd_MWh": LCOEgross,
        "n_years": n_years,
    }
    m.dispose()
    del SOC, Ppv, Ppvmx, Pd, Pc, Pb, Ps, data_Plu, data_Ppvu, data_lambda, data_psi
    import gc
    gc.collect()
    return result
