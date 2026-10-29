"""Température de l'air (ECCC), degrés-jours et loi de Stefan."""
from __future__ import annotations

import numpy as np
import pandas as pd
import requests

API = "https://api.weather.gc.ca/collections/climate-daily/items"
CHAMPS = ["LOCAL_DATE", "MEAN_TEMPERATURE", "MIN_TEMPERATURE", "MAX_TEMPERATURE",
          "SNOW_ON_GROUND", "TOTAL_PRECIPITATION"]


def telecharger_station(identifiant: str, debut: str, fin: str) -> pd.DataFrame:
    lignes, decalage = [], 0
    while True:
        r = requests.get(API, params={
            "CLIMATE_IDENTIFIER": identifiant, "datetime": f"{debut}/{fin}",
            "f": "json", "limit": 5000, "offset": decalage,
            "properties": ",".join(CHAMPS), "sortby": "LOCAL_DATE"}, timeout=120)
        r.raise_for_status()
        feats = r.json()["features"]
        lignes += [f["properties"] for f in feats]
        if len(feats) < 5000:
            break
        decalage += 5000
    df = pd.DataFrame(lignes, columns=CHAMPS)
    df["date"] = pd.to_datetime(df.pop("LOCAL_DATE")).dt.normalize()
    return df.set_index("date").sort_index()


def assembler(series: list[pd.DataFrame]) -> pd.DataFrame:
    """Série quotidienne continue : la première station, comblée par les suivantes."""
    jours = pd.date_range(min(s.index.min() for s in series),
                          max(s.index.max() for s in series), freq="D")
    sortie = pd.DataFrame(index=jours, columns=series[0].columns, dtype="float64")
    sortie["source"] = ""
    for i, s in enumerate(series):
        s = s[~s.index.duplicated()].reindex(jours).apply(pd.to_numeric, errors="coerce")
        manque = sortie["MEAN_TEMPERATURE"].isna() & s["MEAN_TEMPERATURE"].notna()
        for c in series[0].columns:
            sortie.loc[manque, c] = s.loc[manque, c]
        sortie.loc[manque, "source"] = str(i)
    # moyenne quotidienne recalculée par (min+max)/2 si elle manque
    m = sortie["MEAN_TEMPERATURE"].isna()
    sortie.loc[m, "MEAN_TEMPERATURE"] = (sortie.loc[m, "MIN_TEMPERATURE"] + sortie.loc[m, "MAX_TEMPERATURE"]) / 2
    # trous de un à trois jours : interpolation linéaire
    sortie["tair"] = sortie["MEAN_TEMPERATURE"].interpolate(limit=3, limit_area="inside")
    return sortie


def annee_glace(dates: pd.DatetimeIndex) -> np.ndarray:
    """Année de glace : du 1er septembre au 31 août, nommée par l'année du printemps."""
    return np.where(dates.month >= 9, dates.year + 1, dates.year)


def degres_jours(tair: pd.Series) -> pd.DataFrame:
    """Degrés-jours de gel cumulés depuis le 1er septembre (DJG) et de dégel
    cumulés depuis le 1er janvier (DJD)."""
    df = pd.DataFrame({"tair": tair})
    df["annee_glace"] = annee_glace(df.index)
    df["djg"] = df["tair"].clip(upper=0).abs().fillna(0).groupby(df["annee_glace"]).cumsum()
    df["djd"] = df["tair"].clip(lower=0).fillna(0).groupby(df.index.year).cumsum()
    return df


def stefan(djg, alpha: float) -> np.ndarray:
    """Épaisseur de glace (m) par la loi de Stefan, h = alpha * racine(DJG)."""
    return alpha * np.sqrt(np.asarray(djg, dtype="float64"))
