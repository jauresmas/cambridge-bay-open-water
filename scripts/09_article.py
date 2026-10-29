"""09. Article scientifique (docs/article.md, docs/article.html, docs/article.pdf).

Tous les chiffres du texte et des tableaux sont lus dans resultats/ : aucun
n'est tapé à la main. Le PDF est rendu par Microsoft Edge sans interface
s'il est installé.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import html
import importlib.metadata as metadonnees
import os
import platform
import re
import subprocess
import zipfile

os.environ.pop("PROJ_LIB", None)

import numpy as np
import pandas as pd

from cbow import config
from cbow.style import nombre

R = config.RESULTATS
DOCS = config.RACINE / "docs"
DEPOT = "github.com/jauresmas/cambridge-bay-open-water"
MOIS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre",
        "octobre", "novembre", "décembre"]
MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September",
          "October", "November", "December"]
K_EAU = "débâcle optique après l'eau en surface (thermique)"
K_FONTE = "débâcle optique après la fonte (radar)"
K_GLACE = "prise consolidée après la première glace (thermique)"
K_PRISE = "prise, radar et optique"


def _date(doy):
    return pd.Timestamp("2021-01-01") + pd.Timedelta(days=round(doy) - 1)


def jour(doy) -> str:
    """Jour de l'année (année non bissextile) en date : « 3 juillet »."""
    if pd.isna(doy):
        return "non daté"
    d = _date(doy)
    return f"{'1er' if d.day == 1 else d.day} {MOIS[d.month - 1]}"


def day(doy) -> str:
    d = _date(doy)
    return f"{d.day} {MONTHS[d.month - 1]}"


def n(x, d=0):
    if pd.isna(x):
        return "nd"
    return nombre(x, d) if d else f"{x:,.0f}".replace(",", "\u202f")


def en(x, d=0):
    return f"{x:,.{d}f}"


def puissance(x) -> str:
    """9.3e-07 -> « 9 × 10<sup>-7</sup> »."""
    mantisse, exposant = f"{x:.0e}".split("e")
    return f"{mantisse} × 10<sup>{int(exposant)}</sup>"


# ---------------------------------------------------------------------------
def chiffres() -> dict:
    c = {}
    lacs = pd.read_csv(R / "lacs.csv")
    c["n_lacs"] = len(lacs)
    c["greiner_km2"] = float(lacs.loc[lacs.lac_id == 1, "surface_km2"].iloc[0])
    s1 = pd.read_csv(R / "s1_lacs.csv", parse_dates=["date"])
    s2 = pd.read_csv(R / "s2_lacs.csv", parse_dates=["date"])
    ls = pd.read_csv(R / "landsat_lacs.csv", parse_dates=["date"])
    c["n_s1"] = s1[["date", "orbite"]].drop_duplicates().shape[0]
    c["n_s2"] = s2[["date", "orbite"]].drop_duplicates().shape[0]
    c["n_ls"] = ls.scene.nunique()
    # observations utiles de Greiner Lake par an
    obs = {}
    for nom, t, cond in [("s1", s1, s1.objet.astype(str) == "1"),
                         ("s2", s2, (s2.objet.astype(str) == "1") & (s2.part_claire >= config.FRACTION_VALIDE_MIN)),
                         ("ls", ls, (ls.objet.astype(str) == "1") & (ls.part_claire >= 0.6))]:
        x = t[cond].drop_duplicates("date")
        obs[nom] = x.groupby(x.date.dt.year).size()
    c["obs"] = obs

    met = pd.read_csv(R / "meteo_annuelle.csv", parse_dates=["premier_degel", "premier_gel_automne"])
    c["met"] = met
    c["pente"] = float(pd.read_csv(R / "s1_pentes_incidence.csv").pente.median())
    cap = pd.read_csv(R / "phenologie_capteurs.csv", parse_dates=["avant", "apres", "date"])
    cap["objet"] = cap.objet.astype(str)
    fus = pd.read_csv(R / "phenologie_fusion.csv", parse_dates=["date"])
    fus["objet"] = fus.objet.astype(str)
    c["n_lac_annees"] = int(cap[(cap.objet != "mer")][["objet", "annee"]].drop_duplicates().shape[0])
    etapes = []
    for capteur, ev in [("Sentinel-1", "fonte"), ("Landsat TIRS", "eau_surface"), ("Sentinel-2", "debacle"),
                        ("Landsat TIRS", "premiere_glace"), ("Sentinel-2", "prise"), ("Sentinel-1", "prise")]:
        g = cap[(cap.objet != "mer") & (cap.capteur == capteur) & (cap.evenement == ev)]
        d = g.date.dropna().dt.dayofyear
        etapes.append(dict(capteur=capteur, ev=ev, med=d.median(), q1=d.quantile(0.25), q3=d.quantile(0.75),
                           demi=g.demi_largeur_j.median(), datee=100 * g.date.notna().mean()))
    g = fus[(fus.objet != "mer") & (fus.evenement == "prise")]
    d = g.date.dt.dayofyear
    etapes.append(dict(capteur="fusion", ev="prise", med=d.median(), q1=d.quantile(0.25), q3=d.quantile(0.75),
                       demi=g.demi_largeur_j.median(), datee=np.nan))
    c["etapes"] = pd.DataFrame(etapes)
    c["conc"] = pd.read_csv(R / "phenologie_concordance.csv").set_index("comparaison")
    c["prise_etats"] = fus[(fus.evenement == "prise") & (fus.objet != "mer")].etat.value_counts()
    var = pd.read_csv(R / "s1_prise_variantes.csv")
    c["var"] = var
    c["var12"] = var[var.seuil_db == 1.2].set_index("periode")
    c["var_autres"] = var[var.seuil_db != 1.2].ecart_absolu_median_j

    fen = pd.read_csv(R / "fenetre_eau_libre.csv")
    lac = fen[fen.objet.astype(str) != "mer"]
    mer = fen[fen.objet.astype(str) == "mer"].set_index("annee")
    c["eau_libre_med"] = lac.eau_libre_j.median()
    c["eau_libre_q1"], c["eau_libre_q3"] = lac.eau_libre_j.quantile(0.25), lac.eau_libre_j.quantile(0.75)
    par_an = lac.groupby("annee")[["jour_debacle", "jour_prise", "eau_libre_j"]].median()
    c["par_an"] = par_an
    c["mer_an"] = mer
    c["deb_ecart"] = par_an.jour_debacle.max() - par_an.jour_debacle.min()
    c["prise_ecart"] = par_an.jour_prise.max() - par_an.jour_prise.min()
    recent = par_an.index >= 2023
    c["eau_avant"], c["eau_recent"] = par_an.eau_libre_j[~recent].median(), par_an.eau_libre_j[recent].median()
    c["prise_avant"], c["prise_recent"] = par_an.jour_prise[~recent].median(), par_an.jour_prise[recent].median()
    m = met.set_index("annee_glace")
    t = par_an.join(m[["premier_degel", "premier_gel_automne"]], how="inner")
    t["j_degel"] = t.premier_degel.dt.dayofyear
    t["j_gel"] = t.premier_gel_automne.dt.dayofyear
    d = t.dropna(subset=["jour_debacle", "j_degel"])
    c["r_deb_degel"] = float(np.corrcoef(d.jour_debacle, d.j_degel)[0, 1])
    c["delai_degel_deb"] = float((d.jour_debacle - d.j_degel).median())
    p = t.dropna(subset=["jour_prise", "j_gel"])
    c["r_prise_gel"] = float(np.corrcoef(p.jour_prise, p.j_gel)[0, 1])
    c["delai_gel_prise"] = float((p.jour_prise - p.j_gel).median())
    c["n_annees"] = len(d)
    c["gel_avant"] = t.j_gel[t.index < 2023].median()
    c["gel_recent"] = t.j_gel[t.index >= 2023].median()
    g = fen[fen.objet.astype(str) == "1"]
    c["greiner_deb"], c["greiner_prise"] = g.jour_debacle.median(), g.jour_prise.median()
    c["mer_deb"], c["mer_prise"] = mer.jour_debacle.median(), mer.jour_prise.median()
    c["mer_eau"], c["mer_n"] = mer.eau_libre_j.median(), int(mer.eau_libre_j.notna().sum())

    b = pd.read_csv(R / "glace_regime_annees.csv")
    c["regime"] = b
    c["r_posee_stefan"] = float(np.corrcoef(b.glace_stefan_30_avril_m, b.posee)[0, 1])
    c["dec_ecart"] = b.lacs_decembre_db.max() - b.lacs_decembre_db.min()
    c["terre_max"] = b.terre_delta_db.abs().max()
    c["h_min"], c["h_max"] = b.glace_stefan_30_avril_m.min(), b.glace_stefan_30_avril_m.max()
    c["posee_min"], c["posee_max"] = 100 * b.posee.min(), 100 * b.posee.max()

    c["bathy"] = pd.read_csv(R / "bathymetrie_limite.csv").iloc[0]
    c["bsc"] = pd.read_csv(R / "bathymetrie_scores.csv").set_index("modele")
    c["bcl"] = pd.read_csv(R / "bathymetrie_scores_classes.csv")
    c["b10"] = pd.read_csv(R / "bathymetrie_controle_10m.csv").iloc[0]
    ic = pd.read_csv(R / "icesat2_atl24_granules.csv")
    c["atl24"], c["atl24_ete"] = len(ic), int(ic.eau_libre_probable.sum())

    # outils et versions réellement utilisés
    import geopandas as gpd
    import rasterio
    from scipy import stats
    c["python"] = platform.python_version()
    c["versions"] = {p: metadonnees.version(p) for p in ("numpy", "pandas", "scipy", "rasterio", "geopandas",
                                                         "shapely", "pyproj", "scikit-learn", "matplotlib",
                                                         "pytest")}
    c["gdal"] = rasterio.__gdal_version__
    qgz = config.RACINE / "qgis" / "cambridge_bay.qgz"
    with zipfile.ZipFile(qgz) as z:
        qgs = next(x for x in z.namelist() if x.endswith(".qgs"))
        v = re.search(r'version="([^"]+)"', z.read(qgs).decode("utf-8")[:2000]).group(1)
        num, _, nom = v.partition("-")
        c["qgis"] = f"{num} LTR ({nom})" if nom else num
    c["ctrl"] = pd.read_csv(R / "controle_qgis.csv")
    lq = gpd.read_file(R / "qgis" / "cambridge_bay.gpkg", layer="lacs_suivis")
    c["lac_eau_min"], c["lac_eau_max"] = lq.eau_libre_j.min(), lq.eau_libre_j.max()
    c["rho_deb"] = stats.spearmanr(lq.surface_km2, lq.debacle_jour)
    c["rho_eau"] = stats.spearmanr(lq.surface_km2, lq.eau_libre_j)
    return c


# ---------------------------------------------------------------------------
NOM_ETAPE = {("Sentinel-1", "fonte"): ("Fonte : neige humide sur la glace", "Radar Sentinel-1"),
             ("Landsat TIRS", "eau_surface"): ("Eau en surface", "Thermique Landsat"),
             ("Sentinel-2", "debacle"): ("Fin de la débâcle", "Optique Sentinel-2"),
             ("Landsat TIRS", "premiere_glace"): ("Première glace", "Thermique Landsat"),
             ("Sentinel-2", "prise"): ("Prise sous la neige", "Optique Sentinel-2"),
             ("Sentinel-1", "prise"): ("Prise consolidée", "Radar Sentinel-1"),
             ("fusion", "prise"): ("Prise consolidée", "Radar et optique combinés")}


def contenu(c) -> list:
    conc, bsc, li, et = c["conc"], c["bsc"], c["bathy"], c["etapes"].set_index(["capteur", "ev"])

    def e(capteur, ev, col):
        return et.loc[(capteur, ev), col]

    def ec(nom, col="ecart_median_j"):
        return float(conc.loc[nom, col])

    stumpf, foret, lyz = bsc.loc["Stumpf bleu/vert"], bsc.loc["Forêt aléatoire"], bsc.loc["Lyzenga 3 bandes"]
    cl = c["bcl"][c["bcl"].modele == "Stumpf bleu/vert"].set_index("classe")
    b, v, ob, met = c["regime"], c["var12"], c["obs"], c["met"]
    pr = c["prise_etats"]
    s1_av, s1_ap = ob["s1"][ob["s1"].index <= 2021], ob["s1"][(ob["s1"].index >= 2022) & (ob["s1"].index <= 2024)]
    sens = "diminue" if c["r_posee_stefan"] < 0 else "augmente"

    # Tableau 3 : étapes
    t3 = []
    for k in [("Sentinel-1", "fonte"), ("Landsat TIRS", "eau_surface"), ("Sentinel-2", "debacle"),
              ("Landsat TIRS", "premiere_glace"), ("Sentinel-2", "prise"), ("Sentinel-1", "prise"),
              ("fusion", "prise")]:
        r = et.loc[k]
        t3.append([NOM_ETAPE[k][0], NOM_ETAPE[k][1], jour(r.med), f"{jour(r.q1)} au {jour(r.q3)}",
                   f"± {n(r.demi, 1)} j", "" if pd.isna(r.datee) else f"{n(r.datee)} %"])
    # Tableau 4 : années
    t4 = []
    pa, mer = c["par_an"], c["mer_an"]
    for _, r in met.iterrows():
        a = int(r.annee_glace)
        t4.append([str(a), n(r.djg_30_avril), n(r.glace_stefan_30_avril_m, 2),
                   jour(r.premier_degel.dayofyear) if pd.notna(r.premier_degel) else "nd",
                   jour(pa.loc[a, "jour_debacle"]) if a in pa.index else "nd",
                   jour(r.premier_gel_automne.dayofyear) if pd.notna(r.premier_gel_automne) else "nd",
                   jour(pa.loc[a, "jour_prise"]) if a in pa.index else "nd",
                   n(pa.loc[a, "eau_libre_j"]) if a in pa.index else "nd",
                   n(mer.loc[a, "eau_libre_j"]) if a in mer.index else "nd"])
    # Tableau 5 : bathymétrie
    t5 = [[m, n(bsc.loc[m, "eam"], 2), n(bsc.loc[m, "reqm"], 2), n(bsc.loc[m, "biais"], 2), n(bsc.loc[m, "r2"], 2)]
          for m in ("Stumpf bleu/vert", "Lyzenga 3 bandes", "Forêt aléatoire")]
    t5.append([f"Carte affichée (prédiction jusqu'à {n(li.profondeur_fiable_m)} m)", n(li.carte_eam, 2),
               n(li.carte_reqm, 2), n(li.carte_biais, 2), ""])

    blocs = [
        ("titre", "Dater la glace par étapes : débâcle, prise des glaces et bathymétrie côtière autour de "
                  "Cambridge Bay (Nunavut) avec trois capteurs satellitaires, 2017-2025"),
        ("titre_en", "Dating lake ice by stages: break-up, freeze-up and coastal bathymetry around Cambridge "
                     "Bay (Nunavut) from three satellite sensors, 2017-2025"),
        ("auteur", "Jaurès DAA-HINGBANON"),
        ("affil", f"Géomaticien, France. Travail de recherche personnel, sans financement. Code, données "
                  f"dérivées et figures : {DEPOT}. Version d'octobre 2026."),

        ("h2", "Résumé"),
        ("p", f"La débâcle et la prise des glaces des lacs arctiques sont souvent résumées par deux dates par "
              f"an. Nous montrons qu'avec des capteurs différents, ces dates ne désignent pas le même "
              f"événement. Autour de Cambridge Bay (Iqaluktuuttiaq, île Victoria, Nunavut), nous avons suivi "
              f"{c['n_lacs']} lacs de plus de 1 km² et la baie de 2017 à 2025 avec le radar Sentinel-1 "
              f"({n(c['n_s1'])} passages), l'optique Sentinel-2 ({n(c['n_s2'])} passages) et le thermique "
              f"Landsat 8 et 9 ({n(c['n_ls'])} scènes utiles). Chaque transition est datée par l'intervalle "
              f"qui sépare deux observations, ce qui chiffre ce que chaque capteur laisse dans l'ombre. Les "
              f"trois capteurs datent des étapes successives : neige humide sur la glace au radar (médiane : "
              f"{jour(e('Sentinel-1', 'fonte', 'med'))}), eau de fonte en surface au thermique "
              f"({jour(e('Landsat TIRS', 'eau_surface', 'med'))}), disparition de la glace en optique "
              f"({jour(e('Sentinel-2', 'debacle', 'med'))}), puis première glace au thermique "
              f"({jour(e('Landsat TIRS', 'premiere_glace', 'med'))}) et glace consolidée au radar et en "
              f"optique ({jour(e('fusion', 'prise', 'med'))}). Combinés, radar et optique datent la prise à "
              f"± {n(e('fusion', 'prise', 'demi'), 1)} jour. L'eau libre des lacs dure {n(c['eau_libre_med'])} "
              f"jours en médiane ; la prise est plus tardive sur 2023-2025 et suit le premier gel durable de "
              f"l'air (r = {n(c['r_prise_gel'], 2)}). Pendant l'été, Sentinel-2 restitue la bathymétrie de la "
              f"baie avec une erreur absolue moyenne de {n(stumpf.eam, 1)} m entre 0 et 20 m (validation "
              f"croisée par blocs sur les sondages NONNA du Service hydrographique du Canada), de façon fiable "
              f"jusqu'à {n(li.profondeur_fiable_m)} m. En revanche, la séparation de la glace flottante et de "
              f"la glace posée sur le fond par le radar en mode EW échoue : le signal varie à l'inverse de "
              f"l'épaisseur de glace calculée par la loi de Stefan, brouillé par l'état des lacs en début "
              f"d'hiver."),
        ("p", "**Mots-clés :** glace de lac ; phénologie ; Sentinel-1 ; Sentinel-2 ; Landsat ; infrarouge "
              "thermique ; bathymétrie satellitaire ; Arctique canadien."),

        ("h2", "Abstract"),
        ("p", f"Lake ice break-up and freeze-up are often reduced to two dates per year. We show that different "
              f"sensors date different events. Around Cambridge Bay (Iqaluktuuttiaq, Victoria Island, Nunavut), "
              f"we monitored {c['n_lacs']} lakes larger than 1 km² and the bay from 2017 to 2025 with "
              f"Sentinel-1 radar ({en(c['n_s1'])} passes), Sentinel-2 optical imagery ({en(c['n_s2'])} passes) "
              f"and Landsat 8 and 9 thermal imagery ({en(c['n_ls'])} useful scenes). Each transition is dated "
              f"by the interval between two observations, which measures what each sensor misses. The sensors "
              f"date successive stages: wet snow on the ice in radar (median {day(e('Sentinel-1', 'fonte', 'med'))}), "
              f"meltwater at the surface in thermal imagery ({day(e('Landsat TIRS', 'eau_surface', 'med'))}), "
              f"disappearance of the ice in optical imagery ({day(e('Sentinel-2', 'debacle', 'med'))}), then "
              f"first ice in thermal imagery ({day(e('Landsat TIRS', 'premiere_glace', 'med'))}) and "
              f"consolidated ice in radar and optical imagery ({day(e('fusion', 'prise', 'med'))}). Combined, "
              f"radar and optical imagery date freeze-up within ± {en(e('fusion', 'prise', 'demi'), 1)} day. Lakes "
              f"stay open for {en(c['eau_libre_med'])} days (median); freeze-up was later in 2023-2025 and "
              f"follows the first sustained air frost (r = {en(c['r_prise_gel'], 2)}). In summer, Sentinel-2 "
              f"retrieves the bathymetry of the bay with a mean absolute error of {en(stumpf.eam, 1)} m between "
              f"0 and 20 m (spatial block cross-validation against Canadian Hydrographic Service NONNA "
              f"soundings), reliably down to {en(li.profondeur_fiable_m)} m. Separating floating from bedfast "
              f"ice with EW-mode radar fails: the signal moves opposite to Stefan ice thickness, blurred by the "
              f"state of the lakes in early winter."),
        ("p", "**Keywords:** lake ice; phenology; Sentinel-1; Sentinel-2; Landsat; thermal infrared; "
              "satellite-derived bathymetry; Canadian Arctic."),

        ("h2", "1. Introduction"),
        ("p", "La durée du couvert de glace règle une grande part du fonctionnement des lacs arctiques : leur "
              "bilan de chaleur, leur mélange, la lumière disponible sous la glace. Sur la côte, elle fixe la "
              "saison de navigation et la période pendant laquelle l'imagerie optique voit le fond. Ce couvert "
              "répond aux conditions climatiques (Surdu et al., 2014), et le dégel du pergélisol modifie les "
              "lacs et les côtes de l'Arctique canadien. Le suivre chaque année sur des dizaines de lacs n'est "
              "possible que depuis l'espace."),
        ("p", "Chaque famille de capteurs a ses contraintes. Le radar à synthèse d'ouverture voit à travers les "
              "nuages et pendant la nuit polaire ; il sert à suivre la glace de lac depuis une cinquantaine "
              "d'années (Murfitt et Duguay, 2021). Il distingue la glace flottante, rendue brillante par "
              "l'interface entre la glace et l'eau, de la glace posée sur le fond, plus sombre (Duguay et al., "
              "2002 ; Engram et al., 2018), et il détecte la neige humide, qui absorbe le signal (Nagler et al., "
              "2016). Il confond en revanche facilement l'eau agitée par le vent et la glace humide. L'optique "
              "voit nettement l'eau libre, mais ni sous les nuages ni pendant la nuit polaire. L'infrarouge "
              "thermique mesure la température de surface et sépare donc l'eau de la glace froide, au prix de "
              "scènes claires peu nombreuses."),
        ("p", "Ces capteurs sont souvent comparés comme s'ils mesuraient la même chose. Notre hypothèse est "
              "qu'ils datent des étapes différentes d'un même processus, et qu'il faut les combiner étape par "
              "étape plutôt qu'en bloc. Pour le vérifier, nous datons chaque transition par un intervalle borné "
              "par deux observations réelles, ce qui donne aussi, pour chaque capteur, une mesure directe de sa "
              "précision."),
        ("p", "La même fenêtre d'eau libre conditionne la bathymétrie dérivée de l'imagerie multispectrale. Les "
              "modèles de Lyzenga (1978) et de Stumpf et al. (2003) relient la profondeur à l'atténuation "
              "différente des bandes visibles dans l'eau. Ils demandent des sondages pour la calibration, rares "
              "dans l'Arctique, et une eau dégagée de glace pendant une saison courte."),
        ("p", "Nous traitons trois questions sur la région de Cambridge Bay, où la plateforme MOACC suit en "
              "continu la neige, l'atmosphère et le pergélisol :"),
        ("ul", ["(Q1) Peut-on dater la débâcle et la prise des glaces de chaque lac et de la baie, chaque "
                "année, et avec quelle précision selon le capteur et selon la façon de les combiner ?",
                "(Q2) Pendant la fenêtre d'eau libre, jusqu'à quelle profondeur et avec quelle erreur "
                "Sentinel-2 restitue-t-il la bathymétrie côtière, comparé aux sondages hydrographiques ?",
                "(Q3) Le radar d'hiver sépare-t-il la glace flottante de la glace posée sur le fond, et la part "
                "de glace posée suit-elle l'épaisseur de glace donnée par la loi de Stefan ?"]),

        ("h2", "2. Site d'étude"),
        ("p", f"Le hameau de Cambridge Bay (Iqaluktuuttiaq) se trouve sur la côte sud-est de l'île Victoria, "
              f"au bord d'une baie ouverte sur le détroit de Dease (69,1° N, 105,1° O). La zone d'étude couvre "
              f"60 km sur 55 km (figure 1). Le relief y reste inférieur à 200 m et les lacs y sont très "
              f"nombreux. Nous suivons les {c['n_lacs']} lacs de plus de 1 km² entièrement compris dans la zone "
              f"et assez larges pour une grille de 80 m, dont Greiner Lake (Iqaluktuuttiaq, "
              f"{n(c['greiner_km2'])} km²). La Station canadienne de recherche dans "
              f"l'Extrême-Arctique accueille la plateforme MOACC. Entre 2017 et 2025, l'air a cumulé de "
              f"{n(met.djg_30_avril.min())} à {n(met.djg_30_avril.max())} degrés-jours de gel au 30 avril, ce "
              f"qui correspond à une épaisseur de glace de Stefan de {n(c['h_min'], 2)} à {n(c['h_max'], 2)} m "
              f"(section 3.6)."),
        ("fig", "01_zone.png", "Zone d'étude, sur une image Sentinel-2 du 7 août 2024. Contours jaunes : lacs "
                               "suivis ; cadre pointillé : zone de bathymétrie."),

        ("h2", "3. Méthode et outils"),
        ("h3", "3.1 Données"),
        ("p", "Toutes les données sont ouvertes (tableau 1). Les images sont lues par le catalogue STAC du "
              "Planetary Computer de Microsoft, sans compte, en ne téléchargeant que la fenêtre utile de chaque "
              "fichier au format COG (Cloud Optimized GeoTIFF). Les traitements se font sur des grilles UTM 13 N "
              "de 80 m pour les séries, de 40 m pour les cartes radar et de 10 m pour la bathymétrie."),
        ("table", ["Source", "Producteur", "Usage", "Volume"], [
            ["Sentinel-1 EW GRDM, HH", "ESA, Copernicus", "fonte, prise", f"{n(c['n_s1'])} passages"],
            ["Sentinel-2 L2A", "ESA, Copernicus", "débâcle, prise ; bathymétrie",
             f"{n(c['n_s2'])} passages, mars à novembre"],
            ["Landsat 8 et 9, collection 2, température de surface", "USGS", "eau en surface, première glace",
             f"{n(c['n_ls'])} scènes utiles"],
            ["Températures quotidiennes, 3 stations du hameau", "ECCC", "degrés-jours ; filtre de la fonte",
             "2016-2025"],
            ["NONNA-10 et NONNA-100", "Service hydrographique du Canada", "calibration et validation",
             "baie et entrée"],
            ["Plans d'eau ; toponymes", "OpenStreetMap ; BDTC (RNCan)", "contours et noms des lacs",
             f"{c['n_lacs']} lacs"],
        ], "Données utilisées (2017-2025)."),

        ("h3", "3.2 Radar Sentinel-1"),
        ("p", "Sur la zone, Sentinel-1 acquiert surtout en mode EW (Extra Wide), en polarisation HH. Pour chaque "
              "passage, le compte numérique DN est converti en coefficient de rétrodiffusion :"),
        ("eq", "σ<sup>0</sup> = (DN<sup>2</sup> - N) / A<sup>2</sup>", "σ⁰ = (DN² - N) / A²",
         "où A est la table de calibration sigmaNought et N le bruit thermique en distance et en azimut, "
         "interpolés aux pixels lus."),
        ("p", f"L'image est ensuite projetée par les points d'appui du produit, ce qui suffit sur un terrain "
              f"aussi plat. L'angle d'incidence θ varie de 19 à 47° selon l'orbite et pèse plusieurs décibels. "
              f"Pour chaque lac, nous estimons la pente β sur les mois de janvier à avril, quand la glace évolue "
              f"lentement, par une régression du σ⁰ sur θ avec un niveau propre à chaque hiver, puis nous "
              f"ramenons tous les passages à 35° :"),
        ("eq", "σ<sup>0</sup><sub>35</sub> = σ<sup>0</sup>(θ) - β (θ - 35°)", "σ⁰₃₅ = σ⁰(θ) - β (θ - 35°)",
         f"La pente médiane des lacs vaut {n(c['pente'], 3)} dB par degré."),
        ("p", "La fonte est datée par la première baisse de 3 dB sous le niveau médian de février à avril, à "
              "condition qu'elle soit confirmée par l'un des deux passages suivants. Les passages du matin, sur "
              "une neige regelée, et ceux de midi, sur une neige humide, alternent : exiger un état durable "
              "retarderait la date de plusieurs semaines. Une baisse n'est retenue que si la température "
              "moyenne de l'air a dépassé -5 °C dans les trois jours. La prise est datée par la fin de la "
              "variabilité propre à l'eau libre : l'écart médian entre quatre passages successifs passe sous "
              "1,2 dB."),

        ("h3", "3.3 Optique Sentinel-2"),
        ("p", "Chaque passage est lu à 80 m dans les bandes verte (B03) et infrarouge moyen (B11), avec la "
              "carte de classes de scène (SCL) produite par Sen2Cor. On calcule :"),
        ("eq", "NDSI = (ρ<sub>B03</sub> - ρ<sub>B11</sub>) / (ρ<sub>B03</sub> + ρ<sub>B11</sub>)",
         "NDSI = (ρB03 - ρB11) / (ρB03 + ρB11)",
         "où ρ est la réflectance de surface."),
        ("p", "Un pixel est un nuage si la SCL l'indique (ombre, nuage moyen ou haut, cirrus) ou si ρ(B11) "
              "dépasse 0,20 ; de l'eau libre si ρ(B03) est inférieure à 0,08, ou si la SCL le classe en eau "
              "avec ρ(B03) inférieure à 0,20 ; de la glace ou de la neige si le NDSI dépasse 0,42 et ρ(B03) "
              "dépasse 0,10. La part de chaque classe est calculée sur l'intérieur des lacs, à 120 m des rives, "
              "et un passage n'est retenu que si 60 % du lac au moins est vu sans nuage."),

        ("h3", "3.4 Thermique Landsat"),
        ("p", "La température de surface de la collection 2 (bande 10) est retenue hors nuage et ombre selon "
              "le masque QA_PIXEL, à plus de 1 km du nuage le plus proche et avec une incertitude d'au plus "
              "3 K. Une surface entièrement au-dessus de 2 °C contient de l'eau liquide ; une surface "
              "entièrement sous -1 °C est gelée."),

        ("h3", "3.5 Datation par intervalles et fusion"),
        ("p", "Chaque étape est définie par un état ancien et un état nouveau (tableau 2). Pour un lac et une "
              "année, t⁻ est la dernière observation de l'état ancien et t⁺ la première observation de l'état "
              "nouveau après laquelle l'état ancien ne revient presque plus (au plus une fois, ou dans 15 % des "
              "observations suivantes). La date et sa précision sont :"),
        ("eq", "t = (t<sup>-</sup> + t<sup>+</sup>) / 2 ,&nbsp;&nbsp; δ = (t<sup>+</sup> - t<sup>-</sup>) / 2",
         "t = (t⁻ + t⁺) / 2 ;  δ = (t⁺ - t⁻) / 2",
         "La demi-largeur δ mesure ce que le capteur laisse dans l'ombre (nuages, nuit polaire, revisite)."),
        ("p", "Deux capteurs ne sont combinés que s'ils voient la même étape, ce qui est le cas du radar et de "
              "l'optique pour la prise. La date combinée est alors le milieu de l'intersection des deux "
              "intervalles. Si les intervalles ne se recoupent pas, le cas est compté comme discordant et "
              "l'intervalle le plus étroit est conservé."),
        ("table", ["Étape", "Capteur", "État ancien", "État nouveau"], [
            ["Fonte", "Radar", "passage qui précède la détection",
             "σ⁰ à 3 dB ou plus sous l'hiver, confirmé, air au-dessus de -5 °C"],
            ["Eau en surface", "Thermique", "médiane sous 0,5 °C", "toute la surface au-dessus de 2 °C"],
            ["Fin de la débâcle", "Optique", "glace sur 10 % du lac ou plus", "eau libre sur 90 % du lac"],
            ["Première glace", "Thermique", "médiane au-dessus de 0,5 °C", "toute la surface sous -1 °C"],
            ["Prise sous la neige", "Optique", "eau libre sur 50 % du lac ou plus", "glace ou neige sur 90 %"],
            ["Prise consolidée", "Radar", "écart entre passages au-dessus de 1,8 dB", "écart sous 1,2 dB"],
        ], "Critères de chaque étape. Les seuils sont communs à tous les lacs."),

        ("h3", "3.6 Régime de la glace en fin d'hiver"),
        ("p", "Sous la glace flottante, le σ⁰ croît pendant l'hiver ; quand la glace touche le fond, le "
              "contraste de l'interface disparaît et le σ⁰ baisse. Nous comparons donc, pixel par pixel à 40 m, "
              "la médiane d'avril à celle de mi-novembre à mi-décembre. Une hausse d'au moins 1,5 dB signale "
              "une glace flottante, une baisse d'au moins 1,5 dB une glace probablement posée ; entre les deux, "
              "le pixel reste indéterminé. La terre ferme sert de témoin. L'épaisseur de glace attendue au "
              "30 avril vient de la loi de Stefan (Leppäranta, 1993) :"),
        ("eq", "h = α √DJG", "h = α √DJG",
         "où DJG est la somme des degrés-jours de gel depuis le 1er septembre et α un coefficient empirique, "
         "pris égal à 0,024 m par (degré-jour)<sup>1/2</sup>, avec 0,017 et 0,027 en bornes."),
        ("p", "Si la méthode fonctionne, la part de glace posée doit croître avec h, puisque la glace atteint "
              "alors le fond sur une plus grande surface."),

        ("h3", "3.7 Bathymétrie"),
        ("p", "Dix passages d'été sans glace ni nuage sont choisis automatiquement parmi ceux de 2017 à 2025, en "
              "retenant ceux dont le proche infrarouge reste le plus proche de zéro sur l'eau profonde. Le "
              "reflet du soleil est retiré par régression des bandes visibles sur le proche infrarouge (Hedley "
              "et al., 2005), puis les variables sont combinées par médiane. Nous comparons trois modèles : le "
              "rapport de Stumpf et al. (2003),"),
        ("eq", "z = m<sub>1</sub> ln(n ρ<sub>bleu</sub>) / ln(n ρ<sub>vert</sub>) - m<sub>0</sub>",
         "z = m1 ln(n ρbleu) / ln(n ρvert) - m0", "avec n = 1000 ; le modèle log-linéaire de Lyzenga (1978),"),
        ("eq", "z = a<sub>0</sub> + Σ<sub>i</sub> a<sub>i</sub> ln(ρ<sub>i</sub> - ρ<sub>i,∞</sub>)",
         "z = a0 + Σ ai ln(ρi - ρi,∞)",
         "où ρ<sub>i,∞</sub> est la réflectance de l'eau profonde dans les bandes bleue, verte et rouge ; et une "
         "forêt aléatoire sur les mêmes variables, comme borne empirique."),
        ("p", f"La calibration et la validation utilisent les {n(li.n_cellules_100m)} cellules de 100 m de "
              f"NONNA-100 entre 0 et 20 m, où les variables Sentinel-2 sont moyennées. Les cellules sont "
              f"regroupées par blocs de 1,5 km répartis en cinq plis : deux cellules voisines, presque "
              f"identiques, ne peuvent pas servir l'une à apprendre et l'autre à tester. La profondeur limite "
              f"optique est celle au-delà de laquelle le rapport de Stumpf cesse de croître, estimée par un "
              f"modèle à charnière. Enfin, nous cherchons la profondeur prédite au-delà de laquelle plus de "
              f"10 % des cellules sont en réalité plus profondes que 20 m : la carte n'affiche que les valeurs "
              f"en deçà."),

        ("h3", "3.8 Outils"),
        ("p", "La chaîne de traitement est écrite en Python (tableau 3). Elle lit les images par fenêtres, "
              "calibre le radar, classe les pixels, date les étapes et ajuste les modèles de bathymétrie ; "
              "Matplotlib produit les figures 1 à 4, 6 et 7. QGIS sert à trois choses. Il rassemble toutes "
              "les couches du travail dans un projet stylé, consultable sans programmer. Son contrôleur "
              "temporel anime l'eau libre de chaque lac, année par année, à partir d'une couche qui porte les "
              "dates de débâcle et de prise. Sa mise en page produit la carte de la figure 5."),
        ("p", f"QGIS sert enfin de contrôle indépendant du code. Deux étapes de la chaîne ont été refaites dans "
              f"son modeleur graphique : le rapport de Stumpf, avec la calculatrice raster de GDAL, et la "
              f"médiane du radar par lac, avec l'outil de statistiques de zone. Appliqués aux mêmes données que "
              f"la chaîne Python, les deux modèles donnent un écart maximal de "
              f"{puissance(c['ctrl'].ecart_max.iloc[0])} sur {n(c['ctrl'].n.iloc[0])} pixels pour le rapport, "
              f"soit la précision du calcul en simple précision, et un écart "
              f"{'nul' if c['ctrl'].ecart_max.iloc[1] == 0 else 'maximal de ' + n(c['ctrl'].ecart_max.iloc[1], 2) + ' dB'} "
              f"sur les {n(c['ctrl'].n.iloc[1])} médianes de lac."),
        ("table", ["Outil", "Version", "Usage dans ce travail"], [
            ["Python", c["python"], "chaîne de traitement (scripts 00 à 11), tests"],
            ["NumPy, pandas, SciPy",
             f"{c['versions']['numpy']}, {c['versions']['pandas']}, {c['versions']['scipy']}",
             "calcul matriciel, séries temporelles, statistiques"],
            ["rasterio (GDAL)", f"{c['versions']['rasterio']} (GDAL {c['gdal']})",
             "lecture des COG, calibration radar, reprojection, rastérisation"],
            ["GeoPandas, Shapely, pyproj",
             f"{c['versions']['geopandas']}, {c['versions']['shapely']}, {c['versions']['pyproj']}",
             "lacs, masques, projections"],
            ["scikit-learn", c["versions"]["scikit-learn"], "forêt aléatoire, validation croisée"],
            ["Matplotlib", c["versions"]["matplotlib"], "figures 1 à 4, 6 et 7"],
            ["QGIS (PyQGIS, Processing)", c["qgis"],
             "projet cartographique, contrôleur temporel, mise en page de la figure 5, modeleur graphique "
             "(deux modèles et contrôle croisé)"],
            ["pytest", c["versions"]["pytest"], "seize tests des méthodes sur des cas construits"],
            ["API STAC du Planetary Computer", "", "recherche et accès aux images sans compte"],
        ], "Outils utilisés et versions."),
        ("p", f"La chaîne complète (environ 3 Go de téléchargements), le projet QGIS, ses deux modèles et les "
              f"tests sont publiés ({DEPOT}). Les chiffres de cet article sont lus directement dans les "
              f"tableaux de résultats produits par la chaîne."),

        ("h2", "4. Résultats"),
        ("h3", "4.1 Ce que chaque capteur observe"),
        ("p", f"Sur Greiner Lake, le radar fournit {n(s1_av.min())} à {n(s1_av.max())} observations par an "
              f"jusqu'en 2021, puis {n(s1_ap.min())} à {n(s1_ap.max())} de 2022 à 2024, après la perte de "
              f"Sentinel-1B, et {n(ob['s1'].get(2025, np.nan))} en 2025 avec Sentinel-1C. L'optique en fournit "
              f"{n(ob['s2'].min())} à {n(ob['s2'].max())} par an, toutes entre mars et octobre, et le thermique "
              f"{n(ob['ls'].min())} à {n(ob['ls'].max())}, davantage depuis l'arrivée de Landsat 9 (figure 3). "
              f"Le radar est le seul à voir les lacs de novembre à février, quand le soleil est trop bas pour "
              f"l'optique et le thermique. Ces deux capteurs observent surtout au printemps, quand les nuages "
              f"sont rares, et beaucoup moins en été et en automne (figure 2)."),
        ("fig", "02_series_greiner.png", "Greiner Lake vu par les trois capteurs, 2019-2021 : σ⁰ ramené à 35° "
                                         "(radar), parts de glace et d'eau libre (optique), température de "
                                         "surface (thermique). Les bandes colorées encadrent chaque étape "
                                         "détectée."),
        ("h3", "4.2 Les étapes de la débâcle et de la prise"),
        ("p", f"Le tableau 4 résume les {n(c['n_lac_annees'])} couples lac-année. Les étapes se succèdent dans "
              f"le même ordre presque partout : la neige humide apparaît sur la glace vers le "
              f"{jour(e('Sentinel-1', 'fonte', 'med'))}, l'eau en surface vers le "
              f"{jour(e('Landsat TIRS', 'eau_surface', 'med'))}, et la glace disparaît vers le "
              f"{jour(e('Sentinel-2', 'debacle', 'med'))}. À l'automne, la première glace se forme vers le "
              f"{jour(e('Landsat TIRS', 'premiere_glace', 'med'))} et la glace consolidée s'installe vers le "
              f"{jour(e('fusion', 'prise', 'med'))}."),
        ("table", ["Étape", "Capteur", "Date médiane", "1er à 3e quartile", "Précision médiane", "Cas datés"],
         t3, f"Dates des étapes sur les {c['n_lacs']} lacs, 2017-2025 ({n(c['n_lac_annees'])} couples lac-année)."),
        ("p", f"La précision dépend du capteur bien plus que de l'étape. Le radar et l'optique datent leurs "
              f"étapes à quelques jours près (± {n(e('Sentinel-1', 'fonte', 'demi'), 1)} jours pour la fonte, "
              f"± {n(e('Sentinel-2', 'debacle', 'demi'), 1)} jours pour la fin de la débâcle) ; le thermique, "
              f"faute de scènes claires, ne date l'eau en surface qu'à ± {n(e('Landsat TIRS', 'eau_surface', 'demi'))} "
              f"jours et la première glace que dans {n(e('Landsat TIRS', 'premiere_glace', 'datee'))} % des cas. "
              f"L'optique ne date la prise que dans {n(e('Sentinel-2', 'prise', 'datee'))} % des cas : les nuages "
              f"d'automne et le soleil bas laissent peu d'images en octobre, souvent avant que la glace ne soit "
              f"enneigée."),
        ("fig", "03_angles_morts.png", "À gauche, observations utiles par mois et par an sur Greiner Lake. À "
                                       "droite, demi-largeur médiane des intervalles par étape, et part des cas "
                                       "datés."),
        ("p", f"Notre premier essai combinait l'optique et le thermique pour la fin de la débâcle. Leurs dates "
              f"s'écartaient de deux semaines, et les désaccords avaient une cause physique nette. Le 27 mai "
              f"2025, par exemple, toute la surface de Greiner Lake dépasse 2 °C en thermique, alors que "
              f"l'optique la montre couverte de glace jusqu'au 2 juillet : le thermique voit l'eau de fonte qui "
              f"recouvre la glace, pas la disparition de la glace. En médiane, l'eau en surface précède la fin "
              f"de la débâcle de {n(ec(K_EAU))} jours (quartiles : {n(ec(K_EAU, 'ecart_q1_j'))} et "
              f"{n(ec(K_EAU, 'ecart_q3_j'))}), et la fonte radar la précède de {n(ec(K_FONTE))} jours. À "
              f"l'automne, la glace consolidée vient {n(ec(K_GLACE))} jours après la première glace thermique."),
        ("p", f"Pour la prise, le radar et l'optique voient bien la même étape : leurs dates s'écartent de "
              f"{n(ec(K_PRISE, 'ecart_absolu_median_j'))} jours en valeur absolue médiane, avec un biais de "
              f"{n(ec(K_PRISE))} jours. Leur intersection ramène la précision à ± "
              f"{n(e('fusion', 'prise', 'demi'), 1)} jour. Les intervalles restent toutefois disjoints dans "
              f"{int(pr.get('discordant', 0))} cas sur {int(pr.sum())}. Le seuil radar de 1,2 dB, fixé avant "
              f"toute comparaison, donne face à l'optique un biais de {n(v.loc['2017-2020', 'biais_median_j'])} "
              f"jour sur 2017-2020 et de {n(v.loc['2021-2025', 'biais_median_j'])} jours sur 2021-2025 ; les "
              f"seuils de 0,8 à 2,0 dB testés autour de lui donnent des écarts absolus médians de "
              f"{n(c['var_autres'].min())} à {n(c['var_autres'].max())} jours. Le critère reste donc stable "
              f"malgré la baisse de revisite après 2021."),

        ("h3", "4.3 Variabilité d'une année à l'autre"),
        ("p", f"Sur les lacs, l'eau libre dure {n(c['eau_libre_med'])} jours en médiane (quartiles "
              f"{n(c['eau_libre_q1'])} et {n(c['eau_libre_q3'])} jours). La fin de la débâcle varie peu d'une "
              f"année à l'autre ({n(c['deb_ecart'])} jours entre les années extrêmes) et suit le premier dégel "
              f"durable de l'air de {n(c['delai_degel_deb'])} jours en médiane (r = {n(c['r_deb_degel'], 2)} "
              f"sur {c['n_annees']} ans). La prise varie davantage ({n(c['prise_ecart'])} jours) et suit le "
              f"premier gel durable de l'air de {n(c['delai_gel_prise'])} jours (r = {n(c['r_prise_gel'], 2)}). "
              f"Sur 2023-2025, elle survient le {jour(c['prise_recent'])} en médiane, contre le "
              f"{jour(c['prise_avant'])} sur 2017-2022, et l'eau libre passe de {n(c['eau_avant'])} à "
              f"{n(c['eau_recent'])} jours. Le premier gel durable de l'air a lui aussi reculé, du "
              f"{jour(c['gel_avant'])} au {jour(c['gel_recent'])} en médiane (tableau 5, figure 4). Greiner Lake, "
              f"le plus grand, s'ouvre le {jour(c['greiner_deb'])} et gèle le {jour(c['greiner_prise'])} en "
              f"médiane. Dans la baie, l'eau libre dure {n(c['mer_eau'])} jours, du {jour(c['mer_deb'])} au "
              f"{jour(c['mer_prise'])}."),
        ("table", ["Année", "DJG au 30 avril", "h Stefan (m)", "Dégel de l'air", "Fin de débâcle (lacs)",
                   "Gel de l'air", "Prise (lacs)", "Eau libre, lacs (j)", "Eau libre, baie (j)"], t4,
         "Bilan annuel. DJG : degrés-jours de gel cumulés depuis le 1er septembre. Dégel et gel de l'air : "
         "premier jour de cinq jours consécutifs à moyenne positive (ou négative). Dates des lacs : médianes "
         "des lacs. nd : non daté."),
        ("fig", "04_calendrier.png", "Étapes de la débâcle et de la prise des lacs (médiane et quartiles des "
                                     "lacs), eau libre de la baie, premiers dégel et gel durables de l'air."),
        ("p", f"D'un lac à l'autre, la durée médiane de l'eau libre va de {n(c['lac_eau_min'])} à "
              f"{n(c['lac_eau_max'])} jours (figure 5). Les grands lacs s'ouvrent plus tard (corrélation de "
              f"Spearman entre surface et date de fin de débâcle : ρ = {n(c['rho_deb'].statistic, 2)}, "
              f"p {'< 0,001' if c['rho_deb'].pvalue < 0.001 else '= ' + n(c['rho_deb'].pvalue, 3)}), mais la "
              f"durée de l'eau libre ne dépend pas de leur taille (ρ = {n(c['rho_eau'].statistic, 2)}, "
              f"p = {n(c['rho_eau'].pvalue, 2)}) : un lac qui s'ouvre tard gèle aussi plus tard."),
        ("fig", "07_eau_libre_lacs.png", "Durée médiane de l'eau libre par lac, 2017-2025. Carte mise en page "
                                         "dans QGIS à partir du projet publié avec le code."),

        ("h3", "4.4 Glace flottante ou posée : un test qui échoue"),
        ("p", f"La carte du changement de σ⁰ entre décembre et avril montre des centres de lacs qui "
              f"s'éclaircissent et des marges qui s'assombrissent, ce qu'on attend d'une glace flottante au "
              f"centre et posée sur les hauts-fonds (figure 6). Mais d'une année à l'autre, la part de glace "
              f"« posée » ainsi définie, de {n(c['posee_min'])} à {n(c['posee_max'])} % des pixels de lac, "
              f"{sens} quand l'épaisseur de Stefan augmente (r = {n(c['r_posee_stefan'], 2)} sur {len(b)} "
              f"hivers), à l'inverse de l'hypothèse. Le témoin terrestre reste stable : son écart entre "
              f"décembre et avril ne dépasse pas {n(c['terre_max'], 1)} dB. En revanche, le niveau médian des "
              f"lacs en décembre varie de {n(c['dec_ecart'], 1)} dB entre les hivers."),
        ("fig", "06_glace_regime.png", "À gauche, changement du σ⁰ entre décembre 2019 et avril 2020 sur les "
                                       "lacs (rouge : hausse, bleu : baisse). À droite, niveau médian des lacs "
                                       "en début et en fin d'hiver ; étiquettes : épaisseur de Stefan au "
                                       "30 avril."),

        ("h3", "4.5 Bathymétrie de la baie"),
        ("p", f"Le rapport de Stumpf donne une erreur absolue moyenne de {n(stumpf.eam, 2)} m en validation "
              f"croisée par blocs (tableau 6), meilleure que celle du modèle de Lyzenga et proche de celle de "
              f"la forêt aléatoire. L'erreur est la plus faible entre 0 et 2 m "
              f"({n(cl.loc['0-2 m', 'eam'], 1)} m). Les faibles profondeurs sont surestimées (biais de "
              f"{n(cl.loc['0-2 m', 'biais'], 1)} m entre 0 et 2 m) et les fortes sous-estimées "
              f"({n(cl.loc['15-20 m', 'biais'], 1)} m entre 15 et 20 m). Le rapport cesse de croître vers "
              f"{n(li.limite_bleu_vert_m)} m. Dès {n(li.profondeur_fiable_m)} m prédits, plus de 10 % des "
              f"cellules sont en réalité plus profondes que 20 m ; au-delà de {n(li.profondeur_optique_m)} m "
              f"prédits, c'est la majorité. La carte n'affiche donc que les profondeurs prédites jusqu'à "
              f"{n(li.profondeur_fiable_m)} m : sur ces cellules, l'erreur absolue moyenne est de "
              f"{n(li.carte_eam, 1)} m, le biais de {n(li.carte_biais, 1)} m, et "
              f"{n(100 * li.carte_part_plus_20m, 1)} % des cellules affichées sont en fait plus profondes que "
              f"20 m (figure 7). À 10 m de résolution, sur les pixels NONNA-10 de 0 à "
              f"{n(li.limite_bleu_vert_m)} m, l'erreur absolue moyenne atteint {n(c['b10'].eam, 1)} m avec un "
              f"biais de {n(c['b10'].biais, 1)} m."),
        ("table", ["Modèle", "EAM (m)", "EQM (m)", "Biais (m)", "R²"], t5,
         f"Scores de la bathymétrie entre 0 et 20 m, cellules de 100 m hors pli "
         f"({n(li.n_cellules_100m)} cellules). EAM : erreur absolue moyenne ; EQM : erreur quadratique "
         f"moyenne."),
        ("fig", "05_bathymetrie.png", "Bathymétrie Sentinel-2 à 10 m et sondages NONNA-100, nuage de "
                                      "validation croisée et erreur par classe de profondeur."),

        ("h2", "5. Discussion"),
        ("h3", "5.1 Une débâcle, plusieurs dates"),
        ("p", f"Le résultat principal est qu'une « date de débâcle » dépend du capteur qui la mesure. Entre la neige humide vue au radar et la disparition de la glace vue en optique, "
              f"{n(ec(K_FONTE))} jours s'écoulent en médiane ; entre l'eau en surface vue en thermique et cette "
              f"même disparition, {n(ec(K_EAU))} jours. Comparer des dates obtenues avec des capteurs "
              f"différents, ou les fusionner sans précaution, revient donc à mélanger des étapes séparées de "
              f"deux à cinq semaines. La datation par intervalles rend ce problème visible, parce que chaque "
              f"date porte sa propre incertitude et que deux intervalles incompatibles le restent. Elle montre "
              f"aussi ce qu'apporte une combinaison bien choisie : la prise passe de ± "
              f"{n(e('Sentinel-1', 'prise', 'demi'), 1)} jours (radar) à ± {n(e('fusion', 'prise', 'demi'), 1)} "
              f"jour quand l'optique la confirme."),
        ("p", "L'interprétation du signal thermique de juin comme de l'eau de fonte sur la glace reste une "
              "hypothèse. Elle est cohérente avec l'optique, qui voit encore de la glace, mais aucune mesure de "
              "terrain ne la confirme ici. Une partie de l'écart pourrait aussi venir des pixels de rive, plus "
              "chauds, malgré l'érosion de 120 m."),
        ("h3", "5.2 Pourquoi le test de la glace posée échoue"),
        ("p", f"Trois raisons se cumulent. L'épaisseur de Stefan ne varie que de {n(c['h_min'], 2)} à "
              f"{n(c['h_max'], 2)} m sur la période : l'effet attendu sur la surface de glace posée est faible. "
              f"Le niveau des lacs en décembre, qui dépend de la date de prise et de l'épaisseur déjà atteinte, "
              f"varie de {n(c['dec_ecart'], 1)} dB, plus que le signal recherché. Enfin, à environ 90 m de "
              f"résolution, les marges peu profondes des petits lacs se mêlent à la rive et à la glace "
              f"flottante. Une détection fondée sur le moment où chaque pixel s'assombrit, plutôt que sur deux "
              f"composites, et un radar plus fin conviendraient mieux, avec des mesures d'épaisseur de glace "
              f"pour trancher."),
        ("h3", "5.3 Bathymétrie dans une eau arctique"),
        ("p", f"La forêt aléatoire ne fait guère mieux que le rapport de Stumpf ({n(foret.eam, 2)} contre "
              f"{n(stumpf.eam, 2)} m) : la limite vient du signal, pas du modèle. Au-delà d'une douzaine de "
              f"mètres, la lumière qui revient du fond ne se distingue plus de celle de la colonne d'eau, et la "
              f"régression tasse les valeurs vers la moyenne, d'où la surestimation des faibles profondeurs et "
              f"la sous-estimation des fortes. Les cellules de NONNA-100 mêlent par ailleurs des levés d'époques "
              f"différentes, et leurs profondeurs sont rapportées au zéro des cartes, pas au niveau de l'eau le "
              f"jour de l'image."),
        ("h3", "5.4 Limites"),
        ("ul", ["Aucune mesure de terrain n'a été faite : les étapes de la glace ne sont validées que par "
                "l'accord entre capteurs, et la glace posée n'est pas vérifiée.",
                "Les seuils sont communs à tous les lacs et les contours d'OpenStreetMap ne suivent pas les "
                "variations de niveau. La règle de l'eau libre en optique a été révisée en cours de travail : "
                "de l'eau turbide de fin d'été, que Sen2Cor classe en eau mais dont la réflectance verte "
                "approche 0,11, passait pour de la glace (Greiner Lake, août 2024).",
                "Le masque de nuages de Sen2Cor prend souvent la glace fondante pour un nuage : des "
                "observations sont perdues pendant la débâcle, ce qui élargit les intervalles.",
                "Les sondages NONNA servent à la fois à calibrer et à valider. Les blocs spatiaux limitent le "
                "biais d'autocorrélation, sans remplacer un levé indépendant.",
                "Neuf années ne suffisent pas pour établir une tendance climatique."]),
        ("h3", "5.5 Perspectives"),
        ("p", f"Les mesures continues de la plateforme MOACC, des forages de glace et des sondages de lacs "
              f"permettraient de valider les étapes et le régime de la glace. Les sondages de lacs peuvent "
              f"être transformés en bathymétrie et en courbes hypsométriques avec l'extension QGIS LimnoTools, "
              f"que nous avons développée. La RADARSAT Constellation Mission et Sentinel-1C offrent une "
              f"meilleure résolution ou une meilleure revisite pour la glace posée. L'infrarouge thermique "
              f"aéroporté rendrait la première glace et l'eau de fonte visibles sur les petits lacs. "
              f"L'imagerie hyperspectrale aiderait à séparer la couleur de l'eau, liée à la matière organique "
              f"dissoute et à la turbidité, de l'effet de la profondeur, pour dépasser la limite de "
              f"{n(li.profondeur_fiable_m)} m. Enfin, {c['atl24']} passages du lidar ICESat-2 (produit ATL24) "
              f"recoupent la baie, dont {c['atl24_ete']} en août ou septembre : ils permettraient de calibrer "
              f"Sentinel-2 sans sondage, puis de vérifier le résultat sur NONNA, une démarche transposable aux "
              f"côtes arctiques qui n'ont jamais été sondées."),

        ("h2", "6. Conclusion"),
        ("p", f"Le radar, l'optique et le thermique ne datent pas la même chose. Autour de Cambridge Bay, ils "
              f"voient des étapes successives de la débâcle et de la prise, séparées de deux à cinq semaines, "
              f"et ne doivent être combinés que lorsqu'ils voient la même étape. Ainsi combinés, le radar et "
              f"l'optique datent la prise des lacs à ± {n(e('fusion', 'prise', 'demi'), 1)} jour. La fenêtre "
              f"d'eau libre des lacs dure {n(c['eau_libre_med'])} jours en médiane et suit la température de "
              f"l'air, en particulier à l'automne."),
        ("p", f"Pendant cette fenêtre, Sentinel-2 restitue la bathymétrie de la baie jusqu'à environ "
              f"{n(li.profondeur_fiable_m)} m avec une erreur absolue moyenne de l'ordre de 2 m. La séparation "
              f"de la glace flottante et de la glace posée échoue à la résolution du radar EW ; ce résultat "
              f"négatif indique ce qu'il faudrait mesurer sur le terrain pour aller plus loin."),

        ("h2", "Code et données"),
        ("p", f"Code, résultats dérivés et figures : {DEPOT}. Données : Copernicus Sentinel (2017-2025, données "
              f"modifiées) ; U.S. Geological Survey (Landsat, collection 2) ; Environnement et Changement "
              f"climatique Canada ; Service hydrographique du Canada (NONNA, usage non destiné à la "
              f"navigation) ; Ressources naturelles Canada (Base de données toponymiques du Canada), sous "
              f"Licence du gouvernement ouvert du Canada ; contributeurs OpenStreetMap (ODbL)."),

        ("h2", "Références"),
        ("ref", ["Duguay, C. R., Pultz, T. J., Lafleur, P. M. et Drai, D. (2002). RADARSAT backscatter "
                 "characteristics of ice growing on shallow sub-Arctic lakes, Churchill, Manitoba, Canada. "
                 "Hydrological Processes, 16(8), 1631-1644.",
                 "Engram, M., Arp, C. D., Jones, B. M., Ajadi, O. A. et Meyer, F. J. (2018). Analyzing floating "
                 "and bedfast lake ice regimes across Arctic Alaska using 25 years of space-borne SAR imagery. "
                 "Remote Sensing of Environment, 209, 660-676.",
                 "Hedley, J. D., Harborne, A. R. et Mumby, P. J. (2005). Simple and robust removal of sun glint "
                 "for mapping shallow-water benthos. International Journal of Remote Sensing, 26(10), 2107-2112.",
                 "Leppäranta, M. (1993). A review of analytical models of sea-ice growth. Atmosphere-Ocean, "
                 "31(1), 123-138.",
                 "Lyzenga, D. R. (1978). Passive remote sensing techniques for mapping water depth and bottom "
                 "features. Applied Optics, 17(3), 379-383.",
                 "Murfitt, J. et Duguay, C. R. (2021). 50 years of lake ice research from active microwave "
                 "remote sensing: progress and prospects. Remote Sensing of Environment, 264, 112616.",
                 "Nagler, T., Rott, H., Ripper, E., Bippus, G. et Hetzenecker, M. (2016). Advancements for "
                 "snowmelt monitoring by means of Sentinel-1 SAR. Remote Sensing, 8(4), 348.",
                 "Stumpf, R. P., Holderied, K. et Sinclair, M. (2003). Determination of water depth with "
                 "high-resolution satellite imagery over variable bottom types. Limnology and Oceanography, "
                 "48(1, partie 2), 547-556.",
                 "Surdu, C. M., Duguay, C. R., Brown, L. C. et Fernández Prieto, D. (2014). Response of ice cover "
                 "on shallow lakes of the North Slope of Alaska to contemporary climate conditions (1950-2011): "
                 "radar remote-sensing and numerical modeling data analysis. The Cryosphere, 8, 167-180."]),
    ]
    return blocs


# ---------------------------------------------------------------------------
def _num(blocs):
    """Numérote figures, tableaux et équations dans l'ordre d'apparition."""
    f = t = q = 0
    sortie = []
    for b in blocs:
        if b[0] == "fig":
            f += 1
            sortie.append(("fig", b[1], f"Figure {f}. {b[2]}"))
        elif b[0] == "table":
            t += 1
            sortie.append(("table", b[1], b[2], f"Tableau {t}. {b[3]}"))
        elif b[0] == "eq":
            q += 1
            sortie.append(("eq", b[1], b[2], b[3], q))
        else:
            sortie.append(b)
    return sortie


def _sans_balises(s: str) -> str:
    return re.sub(r"<[^>]+>", "", s).replace("&nbsp;", " ")


def en_markdown(blocs) -> str:
    out = []
    for b in _num(blocs):
        t = b[0]
        if t == "titre":
            out.append(f"# {b[1]}\n")
        elif t == "titre_en":
            out.append(f"*{b[1]}*\n")
        elif t == "auteur":
            out.append(f"**{b[1]}**\n")
        elif t == "affil":
            out.append(f"{b[1]}\n")
        elif t in ("h2", "h3"):
            out.append(f"{'#' * int(t[1])} {b[1]}\n")
        elif t == "p":
            out.append(b[1] + "\n")
        elif t in ("ul", "ref"):
            out.append("\n".join(f"- {i}" for i in b[1]) + "\n")
        elif t == "eq":
            out.append(f"> {b[2]}  ({b[4]})\n\n{_sans_balises(b[3])}\n")
        elif t == "fig":
            out.append(f"![{b[2]}](../figures/{b[1]})\n\n*{b[2]}*\n")
        elif t == "table":
            ent, lignes, leg = b[1], b[2], b[3]
            out.append(f"*{leg}*\n\n| " + " | ".join(ent) + " |\n|" + "---|" * len(ent) + "\n"
                       + "\n".join("| " + " | ".join(l) + " |" for l in lignes) + "\n")
    return "\n".join(out)


def _inline(s: str) -> str:
    s = html.escape(s, quote=False)
    s = re.sub(r"&lt;(/?)(sub|sup)&gt;", r"<\1\2>", s)
    return re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)


CSS = """
@page { size: A4; margin: 16mm 17mm 16mm 17mm; }
:root { --encre:#0b0b0b; --encre2:#52514e; --muet:#898781; --filet:#e1e0d9; --accent:#184f95; }
html { background:#fff; }
body { font-family: "Segoe UI", system-ui, sans-serif; color: var(--encre); font-size: 9.8pt;
       line-height: 1.45; max-width: 176mm; margin: 0 auto; padding: 6mm 0; }
h1 { font-size: 17pt; line-height: 1.25; margin: 0 0 2mm; }
.titre_en { font-style: italic; color: var(--encre2); font-size: 10.5pt; margin: 0 0 4mm; text-align: left; }
.auteur { font-weight: 600; font-size: 10.5pt; margin: 0 0 0.5mm; text-align: left; }
.affil { font-size: 8.8pt; color: var(--muet); margin: 0 0 5mm; padding-bottom: 4mm;
         border-bottom: 1px solid var(--filet); text-align: left; }
h2 { font-size: 12pt; margin: 6mm 0 2mm; color: var(--accent); }
h3 { font-size: 10.4pt; margin: 4mm 0 1.5mm; }
h2, h3 { break-after: avoid; page-break-after: avoid; }
p { margin: 0 0 2.3mm; text-align: justify; hyphens: auto; }
ul { margin: 0 0 3mm; padding-left: 5mm; } li { margin-bottom: 1.1mm; }
.eq { display: flex; justify-content: center; align-items: baseline; gap: 10mm; margin: 2.5mm 0 1mm;
      font-family: "Cambria Math", "Cambria", serif; font-size: 11pt; }
.eq .num { color: var(--encre2); font-family: "Segoe UI", sans-serif; font-size: 9.5pt; }
.eqtxt { font-size: 9.3pt; color: var(--encre2); }
figure { margin: 3mm 0 4mm; break-inside: avoid; }
figure img { width: 100%; max-height: 112mm; object-fit: contain; display: block; }
figcaption { font-size: 8.5pt; color: var(--encre2); margin-top: 1.5mm; }
.tab { break-inside: avoid; margin: 2mm 0 4mm; }
.tab .leg { font-size: 8.5pt; color: var(--encre2); margin-bottom: 1.2mm; text-align: left; }
table { border-collapse: collapse; width: 100%; font-size: 8.3pt; }
th, td { border-bottom: 1px solid var(--filet); padding: 1.2mm 1.6mm; text-align: left; vertical-align: top; }
thead th { border-bottom: 1px solid var(--encre2); color: var(--encre2); font-weight: 600; }
.ref li { font-size: 8.6pt; color: var(--encre2); list-style: none; text-indent: -5mm; }
"""


def en_html(blocs) -> str:
    out = ["<!doctype html><html lang='fr'><head><meta charset='utf-8'>",
           "<meta name='viewport' content='width=device-width, initial-scale=1'>",
           "<title>Dater la glace par étapes</title>", f"<style>{CSS}</style></head><body>"]
    for b in _num(blocs):
        t = b[0]
        if t == "titre":
            out.append(f"<h1>{_inline(b[1])}</h1>")
        elif t in ("titre_en", "auteur", "affil"):
            out.append(f"<p class='{t}'>{_inline(b[1])}</p>")
        elif t in ("h2", "h3"):
            out.append(f"<{t}>{_inline(b[1])}</{t}>")
        elif t == "p":
            out.append(f"<p>{_inline(b[1])}</p>")
        elif t in ("ul", "ref"):
            cl = " class='ref'" if t == "ref" else ""
            out.append(f"<ul{cl}>" + "".join(f"<li>{_inline(i)}</li>" for i in b[1]) + "</ul>")
        elif t == "eq":
            out.append(f"<div class='eq'><span>{b[1]}</span><span class='num'>({b[4]})</span></div>"
                       f"<p class='eqtxt'>{b[3]}</p>")
        elif t == "fig":
            out.append(f"<figure><img src='../figures/{b[1]}' alt='{html.escape(b[2])}'>"
                       f"<figcaption>{_inline(b[2])}</figcaption></figure>")
        elif t == "table":
            out.append(f"<div class='tab'><p class='leg'>{_inline(b[3])}</p><table><thead><tr>"
                       + "".join(f"<th>{_inline(h)}</th>" for h in b[1]) + "</tr></thead><tbody>"
                       + "".join("<tr>" + "".join(f"<td>{_inline(x)}</td>" for x in l) + "</tr>" for l in b[2])
                       + "</tbody></table></div>")
    out.append("</body></html>")
    return "\n".join(out)


def pdf(html_path: Path, pdf_path: Path):
    edge = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")
    if not edge.exists():
        print("Edge absent : PDF non produit")
        return
    subprocess.run([str(edge), "--headless", "--disable-gpu", "--no-pdf-header-footer",
                    f"--print-to-pdf={pdf_path}", html_path.resolve().as_uri()],
                   check=True, capture_output=True, timeout=180)


def main():
    blocs = contenu(chiffres())
    DOCS.mkdir(exist_ok=True)
    (DOCS / "article.md").write_text(en_markdown(blocs), encoding="utf-8")
    h = DOCS / "article.html"
    h.write_text(en_html(blocs), encoding="utf-8")
    pdf(h, DOCS / "article.pdf")
    print("article écrit :", DOCS / "article.md")


if __name__ == "__main__":
    main()
