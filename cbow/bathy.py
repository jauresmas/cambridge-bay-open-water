"""Bathymétrie dérivée de Sentinel-2 (SDB) et validation croisée par blocs.

Trois modèles, du plus physique au plus empirique :
- Stumpf et al. (2003) : profondeur linéaire en ln(n R_bleu) / ln(n R_vert) ;
- Lyzenga (1985), forme log-linéaire à trois bandes : profondeur linéaire en
  ln(R_i - R_profond_i) pour le bleu, le vert et le rouge ;
- forêt aléatoire sur les mêmes variables, comme borne empirique.

La validation croisée regroupe les points par blocs carrés : deux points
voisins, presque identiques, ne peuvent pas se trouver l'un dans
l'apprentissage et l'autre dans le test. Sans cela, l'erreur est sous-estimée.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

N_STUMPF = 1000.0
PLANCHER = 1e-4        # réflectance minimale avant logarithme


def deglint(bandes: dict, pir: np.ndarray, profond: np.ndarray) -> dict:
    """Retire le reflet du soleil (Hedley et al., 2005).

    Sur l'eau profonde, chaque bande visible est régressée sur le proche
    infrarouge ; la part liée au PIR est retranchée partout.
    """
    sortie = {}
    sel = profond & np.isfinite(pir)
    pir_min = np.nanpercentile(pir[sel], 1) if sel.sum() > 100 else 0.0
    for nom, b in bandes.items():
        ok = sel & np.isfinite(b)
        # sans variation du PIR sur l'eau profonde (mer calme), rien à retirer
        if ok.sum() > 100 and np.std(pir[ok]) > 2e-4:
            pente = np.polyfit(pir[ok], b[ok], 1)[0]
        else:
            pente = 0.0
        sortie[nom] = b - pente * (pir - pir_min)
    return sortie


def rapport_stumpf(haut: np.ndarray, bas: np.ndarray) -> np.ndarray:
    with np.errstate(divide="ignore", invalid="ignore"):
        return (np.log(N_STUMPF * np.maximum(haut, PLANCHER))
                / np.log(N_STUMPF * np.maximum(bas, PLANCHER)))


def variables(bleu, vert, rouge, profond_ref: dict | None = None) -> dict:
    """Variables explicatives par pixel."""
    v = {"stumpf_bv": rapport_stumpf(bleu, vert), "stumpf_vr": rapport_stumpf(vert, rouge)}
    ref = profond_ref or {"bleu": 0.0, "vert": 0.0, "rouge": 0.0}
    for nom, b in (("bleu", bleu), ("vert", vert), ("rouge", rouge)):
        v[f"ln_{nom}"] = np.log(np.maximum(b - ref[nom], PLANCHER))
    return v


def blocs(x: np.ndarray, y: np.ndarray, taille: float, plis: int, graine=0) -> np.ndarray:
    """Numéro de pli de chaque point, tiré bloc par bloc."""
    bx = np.floor(x / taille).astype("int64")
    by = np.floor(y / taille).astype("int64")
    cle = bx * 1_000_003 + by
    uniques = np.unique(cle)
    rng = np.random.default_rng(graine)
    pli_bloc = rng.permutation(len(uniques)) % plis
    return pli_bloc[np.searchsorted(uniques, cle)]


class Lineaire:
    """Régression linéaire par moindres carrés (une ou plusieurs variables)."""

    def __init__(self, colonnes):
        self.colonnes = list(colonnes)

    def fit(self, df, z):
        A = np.column_stack([np.ones(len(df))] + [df[c].to_numpy() for c in self.colonnes])
        self.coef, *_ = np.linalg.lstsq(A, z, rcond=None)
        return self

    def predict(self, df):
        A = np.column_stack([np.ones(len(df))] + [df[c].to_numpy() for c in self.colonnes])
        return A @ self.coef


class Foret:
    def __init__(self, colonnes, graine=0):
        from sklearn.ensemble import RandomForestRegressor
        self.colonnes = list(colonnes)
        self.m = RandomForestRegressor(n_estimators=200, min_samples_leaf=5,
                                       n_jobs=-1, random_state=graine)

    def fit(self, df, z):
        self.m.fit(df[self.colonnes].to_numpy(), z)
        return self

    def predict(self, df):
        return self.m.predict(df[self.colonnes].to_numpy())


MODELES = {
    "Stumpf bleu/vert": lambda: Lineaire(["stumpf_bv"]),
    "Lyzenga 3 bandes": lambda: Lineaire(["ln_bleu", "ln_vert", "ln_rouge"]),
    "Forêt aléatoire": lambda: Foret(["stumpf_bv", "stumpf_vr", "ln_bleu", "ln_vert", "ln_rouge"]),
}


def validation_croisee(df: pd.DataFrame, fabrique, plis: np.ndarray) -> np.ndarray:
    """Prédiction hors pli de chaque point."""
    pred = np.full(len(df), np.nan)
    z = df["z"].to_numpy()
    for k in np.unique(plis):
        app = plis != k
        m = fabrique().fit(df[app], z[app])
        pred[~app] = m.predict(df[~app])
    return pred


def scores(z: np.ndarray, pred: np.ndarray) -> dict:
    e = pred - z
    ok = np.isfinite(e)
    e, z = e[ok], z[ok]
    if len(e) == 0:
        return dict(n=0, biais=np.nan, eam=np.nan, reqm=np.nan, r2=np.nan)
    return dict(n=int(len(e)), biais=float(e.mean()), eam=float(np.abs(e).mean()),
                reqm=float(np.sqrt((e ** 2).mean())),
                r2=float(1 - (e ** 2).sum() / ((z - z.mean()) ** 2).sum()))


def scores_par_classe(z, pred, bornes=(0, 2, 5, 10, 15, 20)) -> pd.DataFrame:
    """Scores par classe de profondeur, sans R² (peu parlant dans une classe étroite)."""
    lignes = []
    for a, b in zip(bornes[:-1], bornes[1:]):
        m = (z >= a) & (z < b)
        if not m.any():
            continue
        s = scores(z[m], pred[m])
        s.pop("r2")
        s["classe"] = f"{a}-{b} m"
        lignes.append(s)
    return pd.DataFrame(lignes)
