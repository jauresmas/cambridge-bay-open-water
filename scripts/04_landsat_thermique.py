"""04. Température de surface Landsat 8 et 9 (2017-2025) par lac et pour la mer.

Sorties
- data/landsat/st_90m/*.tif : température de surface (°C x 100, int16)
- resultats/landsat_lacs.csv : par scène et par objet, médiane et quantiles
  de la température des pixels clairs, part claire
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np
import pandas as pd
import rasterio

from cbow import config, grille, landsat

DOSSIER = config.DATA / "landsat"
NODATA = -32768


def traiter(scene, g):
    sortie = DOSSIER / "st_90m" / f"{scene['id']}.tif"
    if sortie.exists():
        return None
    t = landsat.temperature_sur_grille(scene, g)
    code = np.where(np.isfinite(t), np.round(t * 100), NODATA).astype("int16")
    grille.ecrire(sortie, code, g, nodata=NODATA)
    with rasterio.open(sortie, "r+") as dst:
        p = scene["properties"]
        dst.update_tags(heure=p["datetime"], plateforme=p["platform"],
                        elevation_soleil=f"{p.get('view:sun_elevation', float('nan')):.2f}")
    return sortie


def telecharger(fils):
    g = grille.Grille(*config.EMPRISE, res=config.RES_LANDSAT)
    (DOSSIER / "st_90m").mkdir(parents=True, exist_ok=True)
    scenes = []
    for an in config.ANNEES:
        scenes += landsat.chercher(f"{an}-03-01", f"{an}-11-30", cache=DOSSIER / f"catalogue_{an}.json")
    print(f"{len(scenes)} scènes Landsat", flush=True)
    erreurs = []
    with ThreadPoolExecutor(fils) as ex:
        futurs = {ex.submit(traiter, s, g): s["id"] for s in scenes}
        for i, f in enumerate(as_completed(futurs), 1):
            try:
                f.result()
            except Exception as e:
                erreurs.append((futurs[f], repr(e)[:200]))
            if i % 50 == 0:
                print(f"  {i}/{len(scenes)} ({len(erreurs)} erreurs)", flush=True)
    for e in erreurs[:20]:
        print("  erreur", e)


def statistiques():
    g = grille.Grille(*config.EMPRISE, res=config.RES_LANDSAT)
    # masques de 80 m rééchantillonnés au plus proche sur la grille de 90 m
    from rasterio.warp import reproject, Resampling
    src = config.DATA / "zone" / "masques_40m.tif"
    with rasterio.open(src) as s:
        m = np.zeros((s.count, *g.forme), "int32")
        for b in range(s.count):
            reproject(s.read(b + 1), m[b], src_transform=s.transform, src_crs=s.crs,
                      dst_transform=g.transform, dst_crs=g.crs, resampling=Resampling.mode)
    lacs = pd.read_csv(config.RESULTATS / "lacs.csv")
    etiq = np.where(np.isin(m[0], lacs.lac_id), m[0], 0)
    etiq[m[1] == 1] = -1
    sel = etiq != 0
    lab = etiq[sel]
    lignes = []
    for f in sorted((DOSSIER / "st_90m").glob("*.tif")):
        with rasterio.open(f) as s:
            v = s.read(1)[sel]
            tags = s.tags()
        ok = v != NODATA
        df = pd.DataFrame(dict(id=lab, t=np.where(ok, v / 100, np.nan)))
        gpe = df.groupby("id")["t"]
        n = gpe.size()
        n_ok = gpe.count()
        q = gpe.quantile([0.1, 0.5, 0.9]).unstack()
        for k in n.index:
            if n_ok[k] < max(10, 0.3 * n[k]):
                continue
            lignes.append(dict(scene=f.stem, date=tags["heure"][:10], heure=tags["heure"],
                               plateforme=tags["plateforme"], objet="mer" if k == -1 else int(k),
                               n=int(n[k]), part_claire=n_ok[k] / n[k],
                               t_p10=q.loc[k, 0.1], t_med=q.loc[k, 0.5], t_p90=q.loc[k, 0.9]))
    tab = pd.DataFrame(lignes)
    tab.to_csv(config.RESULTATS / "landsat_lacs.csv", index=False, float_format="%.2f")
    print(f"{tab.scene.nunique()} scènes utiles, {len(tab)} lignes")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--fils", type=int, default=4)
    ap.add_argument("--stats-seulement", action="store_true")
    a = ap.parse_args()
    if not a.stats_seulement:
        telecharger(a.fils)
    statistiques()
