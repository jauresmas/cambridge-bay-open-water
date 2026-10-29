"""03. Série Sentinel-2 L2A 2017-2025 (mars à novembre), classes et parts par lac.

Chaque passage est lu à 80 m (vert B03, SWIR B11, classes de scène SCL),
enregistré, puis classé pixel par pixel (nuage, eau libre, glace ou neige,
autre). Sur les terres, « glace ou neige » se lit « neige ».

Sorties
- data/s2/bandes_80m/*.tif : B03 et B11 (x 10000), SCL
- resultats/s2_lacs.csv : par passage et par objet (lac, mer, terre), parts
  de chaque classe et part observée sans nuage
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np
import pandas as pd
import rasterio

from cbow import config, grille, s2

DOSSIER = config.DATA / "s2"
NODATA = -32768


def traiter(groupe, g):
    p = groupe[0]["properties"]
    sortie = DOSSIER / "bandes_80m" / f"{p['datetime'][:10]}_R{p['sat:relative_orbit']:03d}.tif"
    if sortie.exists():
        return None
    b = s2.lire_bandes(groupe, g)
    if np.isfinite(b["B03"]).mean() < 0.05:
        return None
    pile = np.stack([
        np.where(np.isfinite(b["B03"]), np.round(b["B03"] * 10000), NODATA),
        np.where(np.isfinite(b["B11"]), np.round(b["B11"] * 10000), NODATA),
        np.where(np.isfinite(b["SCL"]), b["SCL"], 0),
    ]).astype("int16")
    grille.ecrire(sortie, pile, g, nodata=NODATA)
    with rasterio.open(sortie, "r+") as dst:
        dst.update_tags(heure=p["datetime"],
                        zenith=f"{np.mean([s['properties']['s2:mean_solar_zenith'] for s in groupe]):.2f}",
                        nuages=f"{np.mean([s['properties']['eo:cloud_cover'] for s in groupe]):.1f}",
                        scenes=";".join(s["id"] for s in groupe))
    return sortie


def telecharger(fils):
    g = grille.grille(config.RES_S2_SERIE)
    (DOSSIER / "bandes_80m").mkdir(parents=True, exist_ok=True)
    taches = []
    for an in config.ANNEES:
        sc = s2.chercher(f"{an}-03-01", f"{an}-11-30", cache=DOSSIER / f"catalogue_{an}.json")
        taches += s2.acquisitions(sc)
    print(f"{len(taches)} passages Sentinel-2", flush=True)
    faits, erreurs = 0, []
    with ThreadPoolExecutor(fils) as ex:
        futurs = {ex.submit(traiter, t, g): t[0]["id"] for t in taches}
        for i, f in enumerate(as_completed(futurs), 1):
            try:
                if f.result():
                    faits += 1
            except Exception as e:
                erreurs.append((futurs[f], repr(e)[:200]))
            if i % 50 == 0:
                print(f"  {i}/{len(taches)} ({faits} nouveaux, {len(erreurs)} erreurs)", flush=True)
    for e in erreurs[:20]:
        print("  erreur", e)


def lire_classes(fichier: Path) -> tuple[np.ndarray, dict]:
    with rasterio.open(fichier) as src:
        a = src.read().astype("float32")
        tags = src.tags()
    vert = np.where(a[0] == NODATA, np.nan, a[0] / 10000)
    swir = np.where(a[1] == NODATA, np.nan, a[1] / 10000)
    scl = np.where(a[2] == 0, np.nan, a[2])
    return s2.classer(vert, swir, scl), tags


def statistiques():
    masques = config.DATA / "zone" / "masques_80m.tif"
    ids = grille.lire(masques, 1)
    mer = grille.lire(masques, 2).astype(bool)
    eau_brute = grille.lire(masques, 3) > 0
    lacs = pd.read_csv(config.RESULTATS / "lacs.csv")
    etiq = np.where(np.isin(ids, lacs.lac_id), ids, 0)
    etiq[mer] = -1
    etiq[(etiq == 0) & ~mer & ~eau_brute] = -2          # -2 : terre
    sel = etiq != 0
    lab = etiq[sel]
    cles, inv = np.unique(lab, return_inverse=True)
    total = np.bincount(inv)
    lignes = []
    for f in sorted((DOSSIER / "bandes_80m").glob("*.tif")):
        c, tags = lire_classes(f)
        cv = c[sel]
        comptes = np.zeros((len(cles), 5))
        for k in range(5):
            comptes[:, k] = np.bincount(inv, weights=(cv == k), minlength=len(cles))
        date, orb = f.stem.split("_R")
        for j, cle in enumerate(cles):
            vus = total[j] - comptes[j, s2.SANS_DONNEE]
            if vus < 0.5 * total[j]:
                continue
            clair = vus - comptes[j, s2.NUAGE]
            lignes.append(dict(
                date=date, orbite=int(orb), heure=tags.get("heure"),
                zenith=float(tags.get("zenith", "nan")),
                objet={-1: "mer", -2: "terre"}.get(int(cle), int(cle)),
                n=int(total[j]), part_vue=vus / total[j], part_claire=clair / max(vus, 1),
                glace=comptes[j, s2.GLACE] / max(clair, 1),
                eau=comptes[j, s2.EAU] / max(clair, 1),
                autre=comptes[j, s2.AUTRE] / max(clair, 1)))
    tab = pd.DataFrame(lignes)
    tab.to_csv(config.RESULTATS / "s2_lacs.csv", index=False, float_format="%.4f")
    print(f"{tab.date.nunique()} dates, {len(tab)} lignes")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--fils", type=int, default=6)
    ap.add_argument("--stats-seulement", action="store_true")
    a = ap.parse_args()
    if not a.stats_seulement:
        telecharger(a.fils)
    statistiques()
