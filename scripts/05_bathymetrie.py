"""05. Bathymétrie de la baie par Sentinel-2, calibrée et validée sur NONNA.

1. Scènes : passages d'été (tuile 13WDS) sans glace ni nuage sur la baie,
   classés par le reflet résiduel sur l'eau profonde ; on garde les meilleurs.
2. Réflectances à 10 m, reflet retiré (Hedley), variables (rapports de Stumpf,
   logarithmes des bandes), médiane des scènes.
3. Calibration et validation croisée par blocs sur NONNA-100 (cellules de
   100 m), entre 0 et 20 m ; contrôle à 10 m sur NONNA-10.
4. Profondeur limite optique : au-delà, le rapport de Stumpf ne varie plus.
5. Carte à 10 m, masquée au-delà de la limite, et dispersion entre scènes.

Sorties
- data/bathy/scenes/*.tif (réflectances x 10000), variables_10m.tif
- resultats/bathymetrie_sdb_10m.tif, bathymetrie_dispersion_10m.tif
- resultats/bathymetrie_scenes.csv, bathymetrie_scores.csv,
  bathymetrie_scores_classes.csv, bathymetrie_limite.csv,
  bathymetrie_points_100m.csv
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import json

import numpy as np
import pandas as pd
import rasterio
from rasterio.enums import Resampling
from rasterio.warp import reproject

from cbow import bathy, config, grille, nonna, s2, stac

DOSSIER = config.DATA / "bathy"
N_SCENES = 10
BANDES = ("B02", "B03", "B04", "B08", "SCL")
G10 = grille.Grille(*config.EMPRISE_BAIE, res=config.RES_S2_BATHY)
G100 = grille.Grille(*config.EMPRISE_BAIE, res=100.0)
G80 = grille.Grille(*config.EMPRISE_BAIE, res=80.0)


def masque_mer(g):
    """Masque de mer (40 m) ramené sur la grille g au plus proche."""
    with rasterio.open(config.DATA / "zone" / "masques_40m.tif") as src:
        m = np.zeros(g.forme, "uint8")
        reproject(src.read(2).astype("uint8"), m, src_transform=src.transform, src_crs=src.crs,
                  dst_transform=g.transform, dst_crs=g.crs, resampling=Resampling.nearest)
    return m.astype(bool)


def candidats():
    cache = DOSSIER / "catalogue_ete.json"
    scenes = []
    for an in config.ANNEES:
        scenes += stac.chercher(s2.COLLECTION, f"{an}-07-15", f"{an}-09-25",
                                requete={"eo:cloud_cover": {"lt": 15}, "s2:mgrs_tile": {"eq": "13WDS"}},
                                cache=DOSSIER / f"catalogue_ete_{an}.json")
    cache.write_text(json.dumps([s["id"] for s in scenes]), encoding="utf-8")
    return scenes


def trier_scenes(scenes, profond80, mer80):
    """Part claire, part de glace et proche infrarouge sur l'eau profonde, à 80 m.

    Sur l'eau profonde, le proche infrarouge devrait être nul : positif, il
    signale un reflet ou de l'écume ; négatif, une surcorrection atmosphérique
    qui fausse aussi les bandes visibles. On garde les passages où il reste
    proche de zéro. Un passage retraité (deux versions du même produit) n'est
    compté qu'une fois.
    """
    cache = DOSSIER / "triage_scenes.csv"
    if cache.exists():
        t = pd.read_csv(cache)
    else:
        t = _examiner(scenes, profond80, mer80)
        t.to_csv(cache, index=False)
    t["passage"] = t.id.str.slice(0, 37)          # mission, date et orbite
    t = t.sort_values("id").drop_duplicates("passage", keep="last")
    ok = t[(t.part_claire >= 0.995) & (t.part_glace <= 0.002)
           & t.pir_profond.between(-0.003, 0.005)].copy()
    ok["ecart_pir"] = ok.pir_profond.abs()
    return t, ok.sort_values(["ecart_pir", "zenith"]).head(N_SCENES)


def _examiner(scenes, profond80, mer80):
    lignes = []
    for s in scenes:
        b = s2.lire_bandes([s], G80, bandes=("B03", "B11", "B08", "SCL"))
        c = s2.classer(b["B03"], b["B11"], b["SCL"])
        eau = mer80 & (c != s2.SANS_DONNEE)
        if eau.sum() < 0.95 * mer80.sum():
            continue
        clair = (c[eau] != s2.NUAGE).mean()
        glace = (c[eau] == s2.GLACE).mean()
        reflet = float(np.nanmedian(b["B08"][profond80 & (c == s2.EAU)])) if (profond80 & (c == s2.EAU)).any() else np.nan
        lignes.append(dict(id=s["id"], date=s["properties"]["datetime"][:10],
                           zenith=s["properties"]["s2:mean_solar_zenith"],
                           part_claire=clair, part_glace=glace, pir_profond=reflet))
    return pd.DataFrame(lignes)


def lire_scene(id_):
    f = DOSSIER / "scenes" / f"{id_}.tif"
    if not f.exists():
        s = stac._requete("GET", f"{config.STAC_PC}/collections/{s2.COLLECTION}/items/{id_}").json()
        b = s2.lire_bandes([s], G10, bandes=BANDES)
        pile = np.stack([np.where(np.isfinite(b[k]), np.round(b[k] * (1 if k == "SCL" else 10000)),
                                  -32768) for k in BANDES]).astype("int16")
        grille.ecrire(f, pile, G10, nodata=-32768)
    with rasterio.open(f) as src:
        a = src.read().astype("float32")
    a[a == -32768] = np.nan
    out = {k: a[i] / (1 if k == "SCL" else 10000) for i, k in enumerate(BANDES)}
    return out


def agreger(a, facteur=10, min_valides=80):
    h, w = a.shape[0] // facteur, a.shape[1] // facteur
    b = a[:h * facteur, :w * facteur].reshape(h, facteur, w, facteur)
    n = np.isfinite(b).sum(axis=(1, 3))
    with np.errstate(invalid="ignore"):
        m = np.nanmean(b, axis=(1, 3))
    return np.where(n >= min_valides, m, np.nan)


def limite_optique(z, r, zmax=40.0):
    """Profondeur au-delà de laquelle le rapport ne croît plus (modèle à charnière)."""
    ok = np.isfinite(z) & np.isfinite(r) & (z <= zmax)
    z, r = z[ok], r[ok]
    meilleurs = (np.inf, None)
    for zl in np.arange(3.0, zmax - 2, 0.5):
        A = np.column_stack([np.ones_like(z), np.minimum(z, zl)])
        coef, res, *_ = np.linalg.lstsq(A, r, rcond=None)
        sse = ((A @ coef - r) ** 2).sum()
        if sse < meilleurs[0]:
            meilleurs = (sse, zl)
    return meilleurs[1]


def main():
    (DOSSIER / "scenes").mkdir(parents=True, exist_ok=True)
    f10 = nonna.telecharger(G10, 10, DOSSIER / "nonna10_3857.tif")
    f100 = nonna.telecharger(G10, 100, DOSSIER / "nonna100_3857.tif")
    z10 = nonna.profondeur_sur_grille(f10, G10)
    z100 = nonna.profondeur_sur_grille(f100, G100)
    z80 = nonna.profondeur_sur_grille(f100, G80)
    mer80 = masque_mer(G80)
    mer10 = masque_mer(G10)

    t, choisies = trier_scenes(candidats(), (z80 > 30) & mer80, mer80)
    t.to_csv(config.RESULTATS / "bathymetrie_scenes.csv", index=False, float_format="%.4f")
    print(f"{len(t)} passages d'été examinés, {len(choisies)} retenus")
    print(choisies.to_string(index=False))

    profond10 = (np.isfinite(z10) & (z10 > 35)) | (nonna.profondeur_sur_grille(f100, G10) > 35)
    par_scene = []
    eau_votes = []
    for id_ in choisies.id:
        b = lire_scene(id_)
        eau = (b["B08"] < 0.03) & (b["B03"] > b["B08"]) & ~np.isin(b["SCL"], config.S2_SCL_NUAGES)
        eau_votes.append(eau)
        vis = bathy.deglint({"bleu": b["B02"], "vert": b["B03"], "rouge": b["B04"]},
                            b["B08"], profond10 & eau)
        ref = {k: float(np.nanpercentile(vis[k][profond10 & eau], 50)) for k in vis}
        # référence d'eau profonde un peu sous la médiane, pour garder R - R_prof > 0
        ref = {k: v - 0.002 for k, v in ref.items()}
        v = bathy.variables(vis["bleu"], vis["vert"], vis["rouge"], ref)
        for k in v:
            v[k] = np.where(eau, v[k], np.nan)
        par_scene.append(v)
    eau = (np.mean(eau_votes, axis=0) >= 0.5) & mer10
    noms = list(par_scene[0])
    compo = {k: np.where(eau, np.nanmedian(np.stack([p[k] for p in par_scene]), axis=0), np.nan)
             for k in noms}
    grille.ecrire(DOSSIER / "variables_10m.tif", np.stack([compo[k] for k in noms]).astype("float32"),
                  G10, nodata=np.nan)

    # --- calibration et validation à 100 m sur NONNA-100 ----------------------
    agr = {k: agreger(compo[k]) for k in noms}
    xs, ys = G100.centres()
    df = pd.DataFrame({k: agr[k].ravel() for k in noms})
    df["z"] = z100.ravel(); df["x"] = xs.ravel(); df["y"] = ys.ravel()
    df = df.dropna()
    df = df[(df.z >= 0)]
    lim = limite_optique(df.z.to_numpy(), df.stumpf_bv.to_numpy())
    lim_vr = limite_optique(df.z.to_numpy(), df.stumpf_vr.to_numpy())
    print(f"profondeur limite optique : {lim:.1f} m (bleu/vert), {lim_vr:.1f} m (vert/rouge)")
    cal = df[df.z <= config.BATHY_PROF_MAX].copy()
    plis = bathy.blocs(cal.x.to_numpy(), cal.y.to_numpy(), config.BATHY_BLOC_M, config.BATHY_PLIS)
    scores, classes = [], []
    for nom, fab in bathy.MODELES.items():
        pred = bathy.validation_croisee(cal, fab, plis)
        cal[f"pred_{nom}"] = pred
        s = bathy.scores(cal.z.to_numpy(), pred); s["modele"] = nom
        sl = bathy.scores(cal.z.to_numpy()[cal.z <= lim], pred[cal.z.to_numpy() <= lim]);
        s["reqm_sous_limite"] = sl["reqm"]; s["eam_sous_limite"] = sl["eam"]; s["n_sous_limite"] = sl["n"]
        scores.append(s)
        c = bathy.scores_par_classe(cal.z.to_numpy(), pred); c["modele"] = nom
        classes.append(c)
    scores = pd.DataFrame(scores)[["modele", "n", "biais", "eam", "reqm", "r2",
                                   "n_sous_limite", "eam_sous_limite", "reqm_sous_limite"]]
    classes = pd.concat(classes)
    scores.to_csv(config.RESULTATS / "bathymetrie_scores.csv", index=False, float_format="%.3f")
    classes.to_csv(config.RESULTATS / "bathymetrie_scores_classes.csv", index=False, float_format="%.3f")
    cal.to_csv(config.RESULTATS / "bathymetrie_points_100m.csv", index=False, float_format="%.4f")
    print(scores.to_string(index=False))

    # --- carte finale : meilleur modèle physique (Stumpf ou Lyzenga) ----------
    # la forêt aléatoire sert de borne empirique, pas de carte : elle
    # n'extrapole pas hors des profondeurs et des eaux vues en calibration
    lin = scores[scores.modele != "Forêt aléatoire"]
    choix = lin.sort_values("reqm_sous_limite").modele.iloc[0]
    print(f"modèle retenu pour la carte : {choix}")
    m = bathy.MODELES[choix]().fit(cal, cal.z.to_numpy())
    tout = pd.DataFrame({k: compo[k].ravel() for k in noms})
    ok = tout.notna().all(axis=1).to_numpy()
    carte = np.full(G10.forme[0] * G10.forme[1], np.nan, "float32")
    carte[ok] = m.predict(tout[ok])
    carte = carte.reshape(G10.forme)
    # dispersion entre scènes : même modèle appliqué à chaque scène
    preds = []
    for p in par_scene:
        t_s = pd.DataFrame({k: p[k].ravel() for k in noms})
        o = t_s.notna().all(axis=1).to_numpy() & ok
        v = np.full(len(t_s), np.nan, "float32"); v[o] = m.predict(t_s[o])
        preds.append(v.reshape(G10.forme))
    with np.errstate(invalid="ignore"):
        disp = np.nanstd(np.stack(preds), axis=0).astype("float32")
    # --- saturation : à partir de quelle profondeur prédite ne peut-on plus
    # distinguer un fond de l'eau profonde ? Toutes les cellules, profondes
    # comprises (prédictions hors pli pour celles de la calibration).
    df["pred"] = m.predict(df)
    df.loc[cal.index, "pred"] = cal[f"pred_{choix}"]
    sat = []
    for a in range(0, 25):
        s = df[(df.pred >= a) & (df.pred < a + 1)]
        if len(s):
            sat.append(dict(pred_de_m=a, pred_a_m=a + 1, n=len(s), part_plus_20m=(s.z > 20).mean(),
                            z_mediane=s.z.median()))
    sat = pd.DataFrame(sat)
    sat.to_csv(config.RESULTATS / "bathymetrie_saturation.csv", index=False, float_format="%.3f")
    trop = sat[(sat.part_plus_20m >= 0.10) & (sat.n >= 50)]
    z_fiable = float(trop.pred_de_m.min()) if len(trop) else lim
    tres = sat[(sat.part_plus_20m >= 0.50) & (sat.n >= 50)]
    z_profond = float(tres.pred_de_m.min()) if len(tres) else lim
    aff = df[df.pred <= z_fiable]
    sc_carte = bathy.scores(aff.z.to_numpy(), aff.pred.to_numpy())
    print(f"profondeur affichée jusqu'à {z_fiable:g} m ; au-delà de {z_profond:g} m, eau profonde ;"
          f" carte : {sc_carte}")
    pd.DataFrame([dict(limite_bleu_vert_m=lim, limite_vert_rouge_m=lim_vr,
                       profondeur_fiable_m=z_fiable, profondeur_optique_m=z_profond,
                       modele_carte=choix, n_scenes=len(choisies), n_cellules_100m=len(cal),
                       carte_n=sc_carte["n"], carte_reqm=sc_carte["reqm"], carte_eam=sc_carte["eam"],
                       carte_biais=sc_carte["biais"],
                       carte_part_plus_20m=float((aff.z > 20).mean()))]).to_csv(
        config.RESULTATS / "bathymetrie_limite.csv", index=False, float_format="%.3f")

    # classes décidées sur le voisinage de 5 x 5 pixels (50 m) : en eau
    # profonde, le bruit à 10 m fait passer des pixels isolés sous le seuil
    from scipy import ndimage
    brut = carte.copy()
    v = np.isfinite(brut)
    n_v = ndimage.uniform_filter(v.astype("float32"), 5)
    def part(cond):
        return ndimage.uniform_filter((cond & v).astype("float32"), 5) / np.maximum(n_v, 1e-6)
    p_profond = part(brut >= z_profond)
    p_fiable = part(brut <= z_fiable)
    classes_px = np.zeros(G10.forme, "uint8")
    classes_px[v] = 2
    classes_px[v & (brut <= z_fiable) & (p_fiable >= 0.5)] = 1
    classes_px[v & (p_profond >= 0.5)] = 3
    carte = np.where(classes_px == 1, np.clip(brut, 0, None), np.nan).astype("float32")
    grille.ecrire(config.RESULTATS / "bathymetrie_sdb_10m.tif", carte, G10, nodata=np.nan)
    grille.ecrire(config.RESULTATS / "bathymetrie_classes_10m.tif", classes_px, G10, nodata=0)
    grille.ecrire(config.RESULTATS / "bathymetrie_dispersion_10m.tif",
                  np.where(np.isfinite(carte), disp, np.nan).astype("float32"), G10, nodata=np.nan)

    # --- contrôle à 10 m sur NONNA-10 ----------------------------------------
    # pas une validation indépendante : NONNA-100 agrège en partie les mêmes
    # levés ; il mesure la perte de précision quand on passe de 100 m à 10 m
    t10 = pd.DataFrame({k: compo[k].ravel() for k in noms}); t10["z"] = z10.ravel()
    t10 = t10.dropna(); t10 = t10[(t10.z >= 0) & (t10.z <= lim)]
    p10 = m.predict(t10)
    s10 = bathy.scores(t10.z.to_numpy(), p10)
    pd.DataFrame([dict(modele=choix, echelle="10 m (NONNA-10)", **s10)]).to_csv(
        config.RESULTATS / "bathymetrie_controle_10m.csv", index=False, float_format="%.3f")
    print("contrôle NONNA-10 :", {k: round(v, 2) if isinstance(v, float) else v for k, v in s10.items()})


if __name__ == "__main__":
    main()
