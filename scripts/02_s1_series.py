"""02. Série Sentinel-1 EW (HH) 2017-2025 sur la zone, puis statistiques par lac.

Chaque passage (date et orbite relative, tranches assemblées) donne un
sigma0 HH en dB sur la grille de 80 m. Les passages de fin d'hiver (avril)
et de début d'hiver (mi-novembre à mi-décembre) sont aussi calculés à 40 m
pour la carte de la glace ancrée.

Sorties
- data/s1/serie_80m/*.tif, data/s1/cartes_40m/*.tif (dB x 100, int16)
- data/s1/index.csv : un passage par ligne (date, orbite, incidence)
- resultats/s1_lacs.csv : par passage et par lac, médiane et quantiles du
  sigma0, part des pixels sous -18 dB ; mêmes valeurs pour la mer
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import argparse
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np
import pandas as pd
import rasterio

from cbow import config, grille, s1, stac

DOSSIER = config.DATA / "s1"
NODATA = -32768


def passages(scenes):
    groupes = defaultdict(list)
    for s in scenes:
        p = s["properties"]
        if p.get("sar:instrument_mode") != "EW" or "HH" not in p.get("sar:polarizations", []):
            continue
        groupes[(p["datetime"][:10], p["sat:relative_orbit"])].append(s)
    return sorted(groupes.items())


def dans_fenetre(date: str, fenetre) -> bool:
    return fenetre[0] <= date[5:] <= fenetre[1]


def traiter(cle, tranches, g, facteur, dossier):
    date, orbite = cle
    sortie = dossier / f"{date}_R{orbite:03d}.tif"
    if sortie.exists():
        return None
    res = [r for r in (s1.sigma0_sur_grille(t, g, facteur=facteur) for t in tranches) if r]
    if not res:
        return None
    with np.errstate(invalid="ignore"):
        lin = np.nanmean(np.stack([r["sigma0"] for r in res]), axis=0)
    db = s1.en_db(lin)
    code = np.where(np.isfinite(db), np.round(db * 100), NODATA).astype("int16")
    grille.ecrire(sortie, code, g, nodata=NODATA)
    with rasterio.open(sortie, "r+") as dst:
        dst.update_tags(incidence=f"{np.mean([r['incidence'] for r in res]):.2f}",
                        heure=res[0]["date"], passage=res[0]["passage"],
                        plateforme=res[0]["plateforme"], scenes=";".join(r["id"] for r in res))
    return sortie


def telecharger(fils: int):
    scenes = stac.chercher(s1.COLLECTION, "2017-01-01", "2025-12-31",
                           cache=DOSSIER / "catalogue.json")
    tous = passages(scenes)
    print(f"{len(tous)} passages EW HH")
    taches = []
    g80 = grille.grille(config.RES_S1_SERIE)
    g40 = grille.grille(config.RES_S1_CARTE)
    for cle, tranches in tous:
        taches.append((cle, tranches, g80, 2, DOSSIER / "serie_80m"))
        if dans_fenetre(cle[0], config.S1_FIN_HIVER) or dans_fenetre(cle[0], config.S1_DEBUT_HIVER):
            taches.append((cle, tranches, g40, 1, DOSSIER / "cartes_40m"))
    for d in {t[4] for t in taches}:
        d.mkdir(parents=True, exist_ok=True)
    faits, erreurs = 0, []
    with ThreadPoolExecutor(fils) as ex:
        futurs = {ex.submit(traiter, *t): t[0] for t in taches}
        for i, f in enumerate(as_completed(futurs), 1):
            try:
                if f.result():
                    faits += 1
            except Exception as e:  # une scène défectueuse ne bloque pas la série
                erreurs.append((futurs[f], repr(e)[:200]))
            if i % 50 == 0:
                print(f"  {i}/{len(taches)} ({faits} nouveaux, {len(erreurs)} erreurs)", flush=True)
    for e in erreurs[:20]:
        print("  erreur", e)


def index_et_statistiques():
    lignes = []
    for f in sorted((DOSSIER / "serie_80m").glob("*.tif")):
        with rasterio.open(f) as src:
            t = src.tags()
        date, orb = f.stem.split("_R")
        lignes.append(dict(fichier=f.name, date=date, orbite=int(orb), heure=t.get("heure"),
                           passage=t.get("passage"), plateforme=t.get("plateforme"),
                           incidence=float(t.get("incidence", "nan"))))
    index = pd.DataFrame(lignes)
    index.to_csv(DOSSIER / "index.csv", index=False)

    masques = config.DATA / "zone" / "masques_80m.tif"
    ids = grille.lire(masques, 1)
    mer = grille.lire(masques, 2).astype(bool)
    lacs = pd.read_csv(config.RESULTATS / "lacs.csv")
    etiquettes = ids.copy()
    etiquettes[~np.isin(ids, lacs.lac_id)] = 0
    etiquettes[mer] = -1                     # -1 : mer
    cles = [-1] + lacs.lac_id.tolist()
    sel = etiquettes != 0
    lab = etiquettes[sel]
    stats = []
    for _, r in index.iterrows():
        v = grille.lire(DOSSIER / "serie_80m" / r.fichier)[sel].astype("float32")
        ok = v != NODATA
        df = pd.DataFrame(dict(id=lab[ok], db=v[ok] / 100))
        if df.empty:
            continue
        gpe = df.groupby("id")["db"]
        q = gpe.quantile([0.1, 0.5, 0.9]).unstack()
        part = gpe.apply(lambda x: float((x < -18).mean()))
        n = gpe.size()
        for k in cles:
            if k in n.index:
                stats.append(dict(date=r.date, orbite=r.orbite, passage=r.passage,
                                  incidence=r.incidence, objet="mer" if k == -1 else int(k),
                                  n=int(n[k]), db_p10=q.loc[k, 0.1], db_med=q.loc[k, 0.5],
                                  db_p90=q.loc[k, 0.9], part_sous_18=part[k]))
    tab = pd.DataFrame(stats)
    tab.to_csv(config.RESULTATS / "s1_lacs.csv", index=False, float_format="%.3f")
    print(f"{len(index)} passages, {len(tab)} lignes de statistiques")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--fils", type=int, default=6)
    ap.add_argument("--stats-seulement", action="store_true")
    a = ap.parse_args()
    if not a.stats_seulement:
        telecharger(a.fils)
    index_et_statistiques()
