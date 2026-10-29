"""Dates de débâcle et de prise des glaces à partir de séries d'observations.

Principe commun à tous les capteurs : chaque observation est classée dans un
état (« gelé », « ouvert ») ou laissée indécise. La transition est encadrée
par la dernière observation de l'état ancien et la première observation de
l'état nouveau qui ne soit plus contredite ensuite. La date retenue est le
milieu de cet intervalle ; sa demi-largeur mesure la précision que permet le
capteur (nuages, nuit polaire, revisite), c'est-à-dire son angle mort.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class Transition:
    avant: pd.Timestamp | None      # dernière observation de l'état ancien
    apres: pd.Timestamp | None      # première observation durable de l'état nouveau
    n_obs: int

    @property
    def date(self):
        if self.avant is None or self.apres is None:
            return None
        return self.avant + (self.apres - self.avant) / 2

    @property
    def demi_largeur(self) -> float:
        if self.avant is None or self.apres is None:
            return np.nan
        return (self.apres - self.avant).days / 2


def transition(dates, ancien, nouveau, tolerance: int = 1, part: float = 0.15) -> Transition:
    """Passage de l'état `ancien` à l'état `nouveau` (tableaux booléens).

    `apres` est la première observation `nouveau` après laquelle les
    observations `ancien` restantes (bruit, nuage ou voile mal masqué) ne
    dépassent ni `tolerance`, ni `part` des observations décidées qui
    suivent ; `avant` est la dernière observation `ancien` qui la précède.
    """
    d = pd.to_datetime(pd.Series(dates)).reset_index(drop=True)
    a = np.asarray(ancien, bool)
    n = np.asarray(nouveau, bool)
    ordre = np.argsort(d.values, kind="stable")
    d, a, n = d.iloc[ordre].reset_index(drop=True), a[ordre], n[ordre]
    restants = np.cumsum(a[::-1])[::-1]          # observations « ancien » de i à la fin
    decides = np.cumsum((a | n)[::-1])[::-1]     # observations décidées de i à la fin
    for i in np.flatnonzero(n):
        if restants[i] - a[i] <= max(tolerance, part * (decides[i] - 1)):
            precedents = np.flatnonzero(a[:i])
            avant = d[precedents[-1]] if len(precedents) else None
            return Transition(avant, d[i], int((a | n).sum()))
    return Transition(None, None, int((a | n).sum()))


def debacle_s2(obs: pd.DataFrame, annee: int, glace_min=0.1, eau_min=0.9) -> Transition:
    """Fin de la débâcle : la glace (>= 10 %) cède la place à l'eau libre (>= 90 %)."""
    o = obs[(obs.date >= f"{annee}-04-15") & (obs.date <= f"{annee}-08-31")]
    return transition(o.date, o.glace >= glace_min, o.eau >= eau_min)


def prise_s2(obs: pd.DataFrame, annee: int, glace_min=0.9, eau_min=0.5) -> Transition:
    """Prise complète vue en optique : couvert de glace enneigée (>= 90 %)."""
    o = obs[(obs.date >= f"{annee}-08-15") & (obs.date <= f"{annee}-11-30")]
    return transition(o.date, o.eau >= eau_min, o.glace >= glace_min)


def debacle_thermique(obs: pd.DataFrame, annee: int, glace_max=0.5, eau_min=2.0) -> Transition:
    """Fin de la débâcle en thermique : surface du lac à plus de 2 °C."""
    o = obs[(obs.date >= f"{annee}-04-15") & (obs.date <= f"{annee}-08-31")]
    return transition(o.date, o.t_med < glace_max, o.t_p10 >= eau_min)


def prise_thermique(obs: pd.DataFrame, annee: int, eau_min=0.5, glace_max=-1.0) -> Transition:
    """Prise en thermique : toute la surface sous -1 °C (glace, pas de l'eau à 0 °C)."""
    o = obs[(obs.date >= f"{annee}-08-15") & (obs.date <= f"{annee}-11-30")]
    return transition(o.date, o.t_med > eau_min, o.t_p90 < glace_max)


def normaliser_incidence(obs: pd.DataFrame, reference=35.0, mois=(1, 2, 3, 4)) -> tuple[pd.Series, float]:
    """sigma0 ramené à l'incidence de référence (dB).

    La pente (dB par degré) est estimée sur les mois d'hiver, où la glace
    change lentement, par régression du sigma0 sur l'incidence avec un niveau
    propre à chaque hiver.
    """
    o = obs.copy()
    o["hiver"] = o.date.dt.year
    hiv = o[o.date.dt.month.isin(mois)]
    if len(hiv) < 10:
        return o.db_med, 0.0
    X = pd.get_dummies(hiv["hiver"]).astype(float)
    X["inc"] = hiv["incidence"]
    coef, *_ = np.linalg.lstsq(X.to_numpy(), hiv["db_med"].to_numpy(), rcond=None)
    pente = float(coef[-1])
    return o.db_med - pente * (o.incidence - reference), pente


def fonte_s1(obs: pd.DataFrame, annee: int, seuil=-3.0, tair: pd.Series | None = None,
             tair_min=-5.0) -> Transition:
    """Début de fonte sur la glace : sigma0 normalisé à 3 dB sous l'hiver.

    La neige humide absorbe le signal radar : la chute est franche et précède
    la débâcle de plusieurs semaines. Les passages du matin (neige regelée) et
    de midi (neige humide) alternent : on retient la première détection
    confirmée par l'un des deux passages suivants, pas un état durable.
    Si la température de l'air `tair` (moyenne quotidienne) est fournie, une
    baisse n'est retenue que si l'air a dépassé `tair_min` dans les trois
    jours : par grand froid, la neige ne peut pas être humide.
    """
    hiver = obs[(obs.date >= f"{annee}-02-01") & (obs.date <= f"{annee}-04-30")]
    if len(hiver) < 5:
        return Transition(None, None, 0)
    ref = hiver.db_norm.median()
    o = obs[(obs.date >= f"{annee}-04-15") & (obs.date <= f"{annee}-07-31")].sort_values("date")
    humide = ((o.db_norm - ref) <= seuil).to_numpy()
    if tair is not None:
        jours = o.date.dt.normalize()
        doux = np.array([tair[d - pd.Timedelta(days=2):d].max() >= tair_min for d in jours])
        humide &= doux
    dates = o.date.reset_index(drop=True)
    for i in np.flatnonzero(humide):
        if humide[i + 1:i + 3].any():
            return Transition(dates[i - 1] if i > 0 else None, dates[i], len(o))
    return Transition(None, None, len(o))


def prise_s1(obs: pd.DataFrame, annee: int, fenetre=4, seuil_dispersion=1.2) -> Transition:
    """Prise vue au radar : fin de la variabilité de l'eau libre.

    En eau libre, le vent fait varier le sigma0 d'un passage à l'autre de
    plusieurs dB ; sous la glace, le signal devient régulier et croît
    lentement. On cherche le passage durable à une dispersion glissante
    (écart absolu médian sur `fenetre` passages) inférieure au seuil.
    """
    o = obs[(obs.date >= f"{annee}-08-15") & (obs.date <= f"{annee}-12-31")].sort_values("date")
    if len(o) < fenetre + 2:
        return Transition(None, None, len(o))
    diff = o.db_norm.diff().abs()
    disp = diff.rolling(fenetre, min_periods=fenetre).median().shift(-(fenetre - 1))
    calme = disp <= seuil_dispersion
    agite = disp > seuil_dispersion * 1.5
    ok = disp.notna()
    return transition(o.date[ok], agite[ok], calme[ok], tolerance=0)
