"""01. Température de l'air au hameau (ECCC), degrés-jours, glace de Stefan.

Sorties
- resultats/meteo_quotidienne.csv : température moyenne, DJG, DJD, épaisseur
  de glace de Stefan (centrale et fourchette)
- resultats/meteo_annuelle.csv : par année de glace, DJG au 30 avril, date
  du premier dégel durable, DJD au 15 juillet
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd

from cbow import config, meteo

ALPHAS = (0.017, config.STEFAN_ALPHA, 0.027)


def premier_degel(tair: pd.Series, annee: int) -> pd.Timestamp | None:
    """Premier jour d'une suite de cinq jours à moyenne positive après le 1er avril."""
    s = tair[f"{annee}-04-01":f"{annee}-08-31"]
    chaud = (s > 0).astype(int).rolling(5).sum()
    ok = chaud[chaud >= 5]
    return ok.index[0] - pd.Timedelta(days=4) if len(ok) else None


def premier_gel(tair: pd.Series, annee: int) -> pd.Timestamp | None:
    """Premier jour d'une suite de cinq jours à moyenne négative après le 15 août."""
    s = tair[f"{annee}-08-15":f"{annee}-12-31"]
    froid = (s < 0).astype(int).rolling(5).sum()
    ok = froid[froid >= 5]
    return ok.index[0] - pd.Timedelta(days=4) if len(ok) else None


def main():
    cache = config.DATA / "meteo"
    cache.mkdir(parents=True, exist_ok=True)
    series = []
    for ident in config.STATIONS_ECCC:
        f = cache / f"eccc_{ident}.csv"
        if f.exists():
            s = pd.read_csv(f, index_col=0, parse_dates=True)
        else:
            s = meteo.telecharger_station(ident, "2015-09-01", "2025-12-31")
            s.to_csv(f)
        print(f"station {ident} : {s['MEAN_TEMPERATURE'].notna().sum()} jours")
        series.append(s)
    jour = meteo.assembler(series)
    dj = meteo.degres_jours(jour["tair"])
    for a, nom in zip(ALPHAS, ("glace_stefan_bas", "glace_stefan", "glace_stefan_haut")):
        dj[nom] = meteo.stefan(dj["djg"], a)
    dj["neige_au_sol_cm"] = jour["SNOW_ON_GROUND"]
    config.RESULTATS.mkdir(exist_ok=True)
    dj["2016-09-01":].to_csv(config.RESULTATS / "meteo_quotidienne.csv",
                             index_label="date", float_format="%.3f")

    lignes = []
    for an in range(2017, 2026):
        avril = pd.Timestamp(f"{an}-04-30")
        juillet = pd.Timestamp(f"{an}-07-15")
        lignes.append(dict(
            annee_glace=an,
            djg_30_avril=round(dj.loc[avril, "djg"], 0),
            glace_stefan_30_avril_m=round(dj.loc[avril, "glace_stefan"], 2),
            glace_stefan_bas_m=round(dj.loc[avril, "glace_stefan_bas"], 2),
            glace_stefan_haut_m=round(dj.loc[avril, "glace_stefan_haut"], 2),
            premier_degel=premier_degel(dj["tair"], an),
            djd_15_juillet=round(dj.loc[juillet, "djd"], 0),
            premier_gel_automne=premier_gel(dj["tair"], an),
            jours_manquants=int(jour.loc[f"{an - 1}-09-01":f"{an}-08-31", "tair"].isna().sum()),
        ))
    an = pd.DataFrame(lignes)
    an.to_csv(config.RESULTATS / "meteo_annuelle.csv", index=False)
    print(an.to_string(index=False))


if __name__ == "__main__":
    main()
