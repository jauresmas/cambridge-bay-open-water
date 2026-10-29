"""08. Figures de la note et du README (figures/*.png).

python scripts/08_figures.py            toutes les figures
python scripts/08_figures.py zone bathy  seulement celles nommées
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import geopandas as gpd
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import rasterio
from matplotlib.colors import LinearSegmentedColormap, ListedColormap
from matplotlib.lines import Line2D
from matplotlib.patches import Patch, Rectangle
import matplotlib.patheffects as pe

from cbow import config, grille, s2, stac, style
from cbow.style import CAPTEURS, NOMS_CAPTEURS, nombre, virgule

style.appliquer()
R, F = config.RESULTATS, config.FIGURES
KM = virgule(0)
HALO = [pe.withStroke(linewidth=2.2, foreground="#0b0b0b", alpha=0.75)]
N_LACS = len(pd.read_csv(R / "lacs.csv")) if (R / "lacs.csv").exists() else 0
MOIS = ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."]
NOMS_LACS = {1: "Greiner Lake\n(Iqaluktuuttiaq)", 14: "Long Lake", 8: "Ihuuqtuuq", 2: "Kingmitquq",
             15: "Apatalok"}
PASSAGES_ETE = [("S2A_MSIL2A_20240807T190911_R056_T13WDS_20240808T021150",
                 "S2A_MSIL2A_20240807T190911_R056_T13WES_20240808T021150")]


def axes_km(ax, g=None):
    """Graduations en kilomètres UTM, sans notation scientifique."""
    ax.xaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v / 1000:.0f}"))
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v / 1000:.0f}"))
    ax.set_xlabel("x UTM 13 N (km)")
    ax.set_ylabel("y UTM 13 N (km)")
    ax.grid(False)


def echelle(ax, x, y, km=5):
    ax.add_patch(Rectangle((x, y), km * 1000, 250, color=style.ENCRE, lw=0))
    ax.add_patch(Rectangle((x + km * 500, y), km * 500, 250, color="white", lw=0.6, ec=style.ENCRE))
    ax.text(x + km * 500, y + 600, f"{km} km", ha="center", va="bottom", fontsize=8.5, color="white",
            path_effects=HALO)


def rgb_ete(g):
    cache = config.DATA / "zone" / f"rgb_ete_{int(g.res)}m.tif"
    if not cache.exists():
        scenes = [stac._requete("GET", f"{config.STAC_PC}/collections/{s2.COLLECTION}/items/{i}").json()
                  for i in PASSAGES_ETE[0]]
        # chaque tuile est lue à part puis l'est est recalée sur l'ouest dans
        # leur bande de recouvrement : la correction atmosphérique L2A, faite
        # tuile par tuile, laisse sinon un raccord visible (fond de carte seulement)
        ouest = s2.lire_bandes(scenes[:1], g, bandes=("B04", "B03", "B02"))
        est = s2.lire_bandes(scenes[1:], g, bandes=("B04", "B03", "B02"))
        pile = []
        for k in ("B04", "B03", "B02"):
            commun = np.isfinite(ouest[k]) & np.isfinite(est[k])
            gain = np.nanmedian(ouest[k][commun]) / np.nanmedian(est[k][commun]) if commun.any() else 1.0
            pile.append(np.where(np.isfinite(ouest[k]), ouest[k], est[k] * gain))
        grille.ecrire(cache, np.stack(pile).astype("float32"), g, nodata=np.nan)
    with rasterio.open(cache) as src:
        a = src.read()
    rgb = np.clip((a.transpose(1, 2, 0) - 0.005) / 0.16, 0, 1) ** 0.8
    return np.nan_to_num(rgb, nan=1.0)


# ---------------------------------------------------------------------------
def fig_zone():
    g = grille.grille(40.0)
    rgb = rgb_ete(g)
    lacs = gpd.read_file(config.DATA / "zone" / "lacs.gpkg")
    retenus = pd.read_csv(R / "lacs.csv")
    fig, ax = plt.subplots(figsize=(8.2, 7.6))
    ax.imshow(rgb, extent=g.etendue, interpolation="lanczos")
    sel = lacs[lacs.lac_id.isin(retenus.lac_id)]
    sel.boundary.plot(ax=ax, color="#ffd34d", lw=0.7)
    for lid, nom in NOMS_LACS.items():
        if lid in set(sel.lac_id):
            p = sel[sel.lac_id == lid].geometry.iloc[0].representative_point()
            ax.annotate(nom, (p.x, p.y), fontsize=8.5, color="white", ha="center", va="center",
                        fontweight="semibold", path_effects=HALO)
    x0, y0, x1, y1 = config.EMPRISE_BAIE
    ax.add_patch(Rectangle((x0, y0), x1 - x0, y1 - y0, fill=False, ec="white", lw=1.1, ls=(0, (4, 3))))
    from pyproj import Transformer
    hx, hy = Transformer.from_crs(4326, config.CRS, always_xy=True).transform(*config.HAMEAU)
    ax.plot(hx, hy, marker="o", ms=6, mfc="white", mec=style.ENCRE, mew=1.2)
    ax.annotate("Cambridge Bay\n(Iqaluktuuttiaq)", (hx, hy), xytext=(-12, 10), textcoords="offset points",
                ha="right", fontsize=8.5, color="white", fontweight="semibold", path_effects=HALO)
    echelle(ax, config.EMPRISE[2] - 12000, config.EMPRISE[1] + 2500)
    ax.set_xlim(config.EMPRISE[0], config.EMPRISE[2]); ax.set_ylim(config.EMPRISE[1], config.EMPRISE[3])
    axes_km(ax)
    ax.set_title(f"Zone d'étude : {len(retenus)} lacs de plus de 1 km², la baie et son entrée")
    ax.legend(handles=[Line2D([], [], color="#e0a800", lw=1.4, label="lac suivi (contour OSM)"),
                       Line2D([], [], color=style.ENCRE_2, lw=1.1, ls=(0, (4, 3)), label="zone de bathymétrie")],
              loc="upper left", fontsize=8, frameon=True, facecolor="white", framealpha=0.9,
              edgecolor="none")
    fig.text(0.01, -0.01, "Fond : Sentinel-2 L2A du 7 août 2024 (Copernicus). Lacs : OpenStreetMap. "
             "Toponymes : BDTC (Ressources naturelles Canada).", fontsize=7.5, color=style.MUET)
    style.enregistrer(fig, F / "01_zone.png")


# ---------------------------------------------------------------------------
def fig_series_greiner(lac="1", annees=(2019, 2020, 2021)):
    s1 = pd.read_csv(R / "s1_lacs.csv", parse_dates=["date"])
    s2t = pd.read_csv(R / "s2_lacs.csv", parse_dates=["date"])
    ls = pd.read_csv(R / "landsat_lacs.csv", parse_dates=["date"])
    pentes = pd.read_csv(R / "s1_pentes_incidence.csv")
    cap = pd.read_csv(R / "phenologie_capteurs.csv", parse_dates=["avant", "apres", "date"])
    for t in (s1, s2t, ls, pentes, cap):
        t["objet"] = t["objet"].astype(str)
    p = float(pentes.loc[pentes.objet == lac, "pente"].iloc[0])
    o1 = s1[s1.objet == lac].copy(); o1["db_norm"] = o1.db_med - p * (o1.incidence - 35)
    o2 = s2t[(s2t.objet == lac) & (s2t.part_claire >= config.FRACTION_VALIDE_MIN)]
    ol = ls[ls.objet == lac]
    debut, fin = pd.Timestamp(f"{annees[0]}-01-01"), pd.Timestamp(f"{annees[-1]}-12-31")
    fig, axs = plt.subplots(3, 1, figsize=(10, 7.2), sharex=True, gridspec_kw=dict(hspace=0.18))
    a = axs[0]
    m = (o1.date >= debut) & (o1.date <= fin)
    a.plot(o1.date[m], o1.db_norm[m], "o", ms=2.6, color=CAPTEURS["Sentinel-1"], alpha=0.85)
    a.set_ylabel("σ⁰ HH à 35° (dB)"); a.yaxis.set_major_formatter(virgule(0))
    a.set_title("Radar Sentinel-1 : la glace flottante s'éclaircit tout l'hiver, la neige humide l'éteint")
    a = axs[1]
    m = (o2.date >= debut) & (o2.date <= fin)
    a.plot(o2.date[m], 100 * o2.glace[m], "o", ms=3, color=CAPTEURS["Sentinel-2"], label="glace ou neige")
    a.plot(o2.date[m], 100 * o2.eau[m], "s", ms=2.6, mfc="white", mec=CAPTEURS["Sentinel-2"], label="eau libre")
    a.set_ylabel("part du lac (%)"); a.set_ylim(-5, 105)
    a.legend(loc="center left", fontsize=8, ncol=1)
    a.set_title("Optique Sentinel-2 : aveugle de novembre à février (soleil trop bas) et sous les nuages")
    a = axs[2]
    m = (ol.date >= debut) & (ol.date <= fin)
    a.plot(ol.date[m], ol.t_med[m], "o", ms=3, color=CAPTEURS["Landsat TIRS"])
    a.axhline(0, color=style.AXE, lw=0.8)
    a.set_ylabel("surface (°C)"); a.yaxis.set_major_formatter(virgule(0))
    a.set_title("Thermique Landsat : distingue l'eau à 0 °C de la glace plus froide, mais rarement sans nuage")
    c = cap[(cap.objet == lac) & cap.date.notna()]
    teintes = {"debacle": style.ENCRE, "prise": style.ENCRE_2, "fonte": CAPTEURS["Sentinel-1"]}
    for _, r in c.iterrows():
        if not (debut <= r.date <= fin):
            continue
        ax = {"Sentinel-1": axs[0], "Sentinel-2": axs[1], "Landsat TIRS": axs[2]}[r.capteur]
        ax.axvspan(r.avant, r.apres, color=CAPTEURS[r.capteur], alpha=0.16, lw=0)
    axs[2].xaxis.set_major_locator(mdates.MonthLocator(bymonth=[1, 4, 7, 10]))
    axs[2].xaxis.set_major_formatter(plt.FuncFormatter(
        lambda v, _: f"{MOIS[mdates.num2date(v).month - 1]} {mdates.num2date(v).year}"))
    fig.text(0.01, 0.005, "Bandes colorées : intervalle qui encadre chaque événement détecté "
             "(dernière observation avant, première après).", fontsize=7.5, color=style.MUET)
    fig.suptitle("Greiner Lake (Iqaluktuuttiaq), 42 km² : trois capteurs, trois angles morts",
                 x=0.01, ha="left", fontsize=12, fontweight="semibold")
    style.enregistrer(fig, F / "02_series_greiner.png")


# ---------------------------------------------------------------------------
def fig_angles_morts():
    s2t = pd.read_csv(R / "s2_lacs.csv", parse_dates=["date"])
    ls = pd.read_csv(R / "landsat_lacs.csv", parse_dates=["date"])
    s1 = pd.read_csv(R / "s1_lacs.csv", parse_dates=["date"])
    am = pd.read_csv(R / "angles_morts.csv")
    n_ans = len(config.ANNEES)
    # jours par mois et par an où l'objet est observable (Greiner Lake)
    def par_mois(t, cond):
        d = t[cond].drop_duplicates("date").date
        return d.dt.month.value_counts().reindex(range(1, 13), fill_value=0) / n_ans
    g = "1"
    obs = {
        "Sentinel-1": par_mois(s1, s1.objet.astype(str) == g),
        "Sentinel-2": par_mois(s2t, (s2t.objet.astype(str) == g) & (s2t.part_claire >= config.FRACTION_VALIDE_MIN)),
        "Landsat TIRS": par_mois(ls, (ls.objet.astype(str) == g) & (ls.part_claire >= 0.6)),
    }
    fig, axs = plt.subplots(1, 2, figsize=(12, 4.3), gridspec_kw=dict(width_ratios=[1.25, 1], wspace=0.62))
    a = axs[0]
    l = 0.26
    for i, (c, v) in enumerate(obs.items()):
        a.bar(np.arange(1, 13) + (i - 1) * l, v.values, width=l - 0.03, color=CAPTEURS[c],
              label=NOMS_CAPTEURS[c])
    a.set_xticks(range(1, 13)); a.set_xticklabels(MOIS, fontsize=8)
    a.set_ylabel("observations utiles par mois")
    a.legend(fontsize=8, loc="upper center", bbox_to_anchor=(0.5, -0.1), ncol=3)
    a.set_title("Ce que chaque capteur voit au fil de l'année (Greiner Lake)")
    a.grid(axis="x", visible=False)
    a = axs[1]
    lignes = [("Sentinel-1", "fonte", "fonte (neige humide), radar"),
              ("Landsat TIRS", "eau_surface", "eau en surface, thermique"),
              ("Sentinel-2", "debacle", "fin de débâcle, optique"),
              ("Landsat TIRS", "premiere_glace", "première glace, thermique"),
              ("Sentinel-2", "prise", "prise enneigée, optique"),
              ("Sentinel-1", "prise", "prise consolidée, radar"),
              ("fusion", "prise", "prise, radar et optique")]
    y = np.arange(len(lignes))[::-1]
    for yy, (c, ev, lab) in zip(y, lignes):
        r = am[(am.capteur == c) & (am.evenement == ev)]
        if r.empty:
            continue
        v = float(r.demi_largeur_mediane_j.iloc[0])
        a.barh(yy, v, height=0.62, color=CAPTEURS[c])
        part = r.part_datee.iloc[0]
        txt = f"± {nombre(v, 1)} j" + ("" if pd.isna(part) else f"  ({part * 100:.0f} % datés)")
        a.text(v + 0.3, yy, txt, va="center", fontsize=8, color=style.ENCRE_2)
    a.set_yticks(y); a.set_yticklabels([l[2] for l in lignes], fontsize=8.5)
    a.set_xlabel("demi-largeur médiane de l'intervalle (jours)")
    a.set_title(f"Précision de datation par étape ({N_LACS} lacs et mer, 2017-2025)")
    a.grid(axis="y", visible=False); a.set_xlim(0, a.get_xlim()[1] * 1.35)
    style.enregistrer(fig, F / "03_angles_morts.png")


# ---------------------------------------------------------------------------
def fig_calendrier():
    fen = pd.read_csv(R / "fenetre_eau_libre.csv")
    an = pd.read_csv(R / "meteo_annuelle.csv", parse_dates=["premier_degel", "premier_gel_automne"])
    lacs = fen[fen.objet.astype(str) != "mer"]
    cols = ["jour_fonte", "jour_eau_surface", "jour_debacle", "jour_premiere_glace", "jour_prise"]
    med = lacs.groupby("annee")[cols].median()
    q1 = lacs.groupby("annee")[["jour_debacle", "jour_prise"]].quantile(0.25)
    q3 = lacs.groupby("annee")[["jour_debacle", "jour_prise"]].quantile(0.75)
    mer = fen[fen.objet.astype(str) == "mer"].set_index("annee")
    th = CAPTEURS["Landsat TIRS"]
    fig, ax = plt.subplots(figsize=(10.5, 5.0))
    for y, r in med.iterrows():
        if np.isfinite(r.jour_debacle) and np.isfinite(r.jour_prise):
            ax.plot([r.jour_debacle, r.jour_prise], [y, y], color="#6da7ec", lw=6, solid_capstyle="butt")
            for c in ("jour_debacle", "jour_prise"):
                ax.plot([q1.loc[y, c], q3.loc[y, c]], [y, y], color="#0d366b", lw=1.3)
        if np.isfinite(r.jour_fonte):
            ax.plot(r.jour_fonte, y, marker="v", color=CAPTEURS["Sentinel-1"], ms=6.5, ls="")
        for c in ("jour_eau_surface", "jour_premiere_glace"):
            if np.isfinite(r[c]):
                ax.plot(r[c], y, marker="D", mfc="white", mec=th, mew=1.4, ms=5.5, ls="")
        if y in mer.index:
            m = mer.loc[y]
            if np.isfinite(m.jour_debacle) and np.isfinite(m.jour_prise):
                ax.plot([m.jour_debacle, m.jour_prise], [y + 0.3, y + 0.3], color="#184f95", lw=3,
                        solid_capstyle="butt", alpha=0.7)
    for _, r in an.iterrows():
        if pd.notna(r.premier_degel):
            ax.plot(r.premier_degel.dayofyear, r.annee_glace - 0.32, marker="|", color="#c63b3b", ms=9, mew=1.8)
        if pd.notna(r.premier_gel_automne):
            ax.plot(r.premier_gel_automne.dayofyear, r.annee_glace - 0.32, marker="|", color="#256abf",
                    ms=9, mew=1.8)
    jours = pd.to_datetime([f"2021-{m:02d}-01" for m in range(5, 13)]).dayofyear
    ax.set_xticks(jours); ax.set_xticklabels(["1er " + MOIS[m - 1] for m in range(5, 13)], fontsize=8.5)
    ax.set_xlim(118, 345); ax.invert_yaxis()
    ax.set_yticks(med.index); ax.set_yticklabels(med.index)
    ax.grid(axis="y", visible=False)
    ax.legend(handles=[
        Line2D([], [], color="#6da7ec", lw=6, label=f"lacs : eau libre, médiane des {N_LACS} lacs"),
        Line2D([], [], color="#0d366b", lw=1.3, label="lacs : quartiles des dates"),
        Line2D([], [], color="#184f95", lw=3, alpha=0.7, label="baie et détroit : eau libre"),
        Line2D([], [], marker="v", color=CAPTEURS["Sentinel-1"], ls="", label="fonte sur la glace (radar)"),
        Line2D([], [], marker="D", mfc="white", mec=th, mew=1.4, ls="",
               label="eau en surface, puis première glace\n(thermique)"),
        Line2D([], [], marker="|", color="#c63b3b", ls="", ms=9, mew=1.8, label="air : premier dégel durable"),
        Line2D([], [], marker="|", color="#256abf", ls="", ms=9, mew=1.8, label="air : premier gel durable")],
        fontsize=7.8, loc="center left", bbox_to_anchor=(1.01, 0.5))
    ax.set_title("La fenêtre d'eau libre et ses étapes, année par année")
    style.enregistrer(fig, F / "04_calendrier.png")


# ---------------------------------------------------------------------------
def fig_bathy():
    from cbow import nonna
    g = grille.Grille(*config.EMPRISE_BAIE, res=10.0)
    sdb = grille.lire(R / "bathymetrie_sdb_10m.tif")
    cls = grille.lire(R / "bathymetrie_classes_10m.tif")
    z100 = nonna.profondeur_sur_grille(config.DATA / "bathy" / "nonna100_3857.tif", g)
    li = pd.read_csv(R / "bathymetrie_limite.csv").iloc[0]
    zf, zp = float(li.profondeur_fiable_m), float(li.profondeur_optique_m)
    pts = pd.read_csv(R / "bathymetrie_points_100m.csv")
    sc = pd.read_csv(R / "bathymetrie_scores.csv")
    cl = pd.read_csv(R / "bathymetrie_scores_classes.csv")
    rgb = rgb_ete(grille.Grille(*config.EMPRISE_BAIE, res=20.0))
    cmap = LinearSegmentedColormap.from_list("prof", style.BLEU)
    gris = ListedColormap(["#00000000", "#00000000", "#c3c2b7", "#52514e"])
    fig = plt.figure(figsize=(12, 9.4))
    gs = fig.add_gridspec(3, 3, height_ratios=[1.25, 0.06, 1], hspace=0.42, wspace=0.32)
    zoom = (484000, 506000, 7647000, 7668500)
    for k in range(2):
        a = fig.add_subplot(gs[0, k])
        a.imshow(rgb, extent=g.etendue)
        if k == 0:
            a.imshow(np.ma.masked_equal(cls, 0), extent=g.etendue, cmap=gris, vmin=0, vmax=3,
                     interpolation="nearest")
            h = a.imshow(sdb, extent=g.etendue, cmap=cmap, vmin=0, vmax=zp, interpolation="nearest")
            a.set_title(f"Sentinel-2, 10 m (affiché jusqu'à {nombre(zf, 0)} m)", fontsize=9.5)
            echelle(a, zoom[0] + 1500, zoom[2] + 1200, km=2)
        else:
            prof = np.where(z100 > zp, 3, np.where(z100 > zf, 2, 0)).astype(float)
            prof[~np.isfinite(z100)] = 0
            a.imshow(np.ma.masked_equal(prof, 0), extent=g.etendue, cmap=gris, vmin=0, vmax=3,
                     interpolation="nearest")
            a.imshow(np.where(z100 <= zf, z100, np.nan), extent=g.etendue, cmap=cmap, vmin=0, vmax=zp,
                     interpolation="nearest")
            a.set_title("Sondages NONNA-100 (mêmes classes)", fontsize=9.5)
        a.set_xlim(zoom[0], zoom[1]); a.set_ylim(zoom[2], zoom[3]); axes_km(a)
    ca = fig.add_subplot(gs[1, :2])
    cb = fig.colorbar(h, cax=ca, orientation="horizontal")
    cb.set_label(f"profondeur (m). Gris clair : {nombre(zf, 0)} à {nombre(zp, 0)} m, incertain ; "
                 f"gris foncé : eau trop profonde pour l'optique")
    cb.ax.xaxis.set_major_formatter(virgule(0))
    a = fig.add_subplot(gs[0, 2])
    meilleur = str(li.modele_carte)
    col = f"pred_{meilleur}"
    a.hexbin(pts.z, pts[col], gridsize=45, extent=(0, 20, -2, 22), cmap=LinearSegmentedColormap.from_list(
        "d", ["#f0efec"] + style.BLEU[2:]), mincnt=1, linewidths=0)
    a.plot([0, 20], [0, 20], color=style.ENCRE, lw=0.8)
    a.axhline(zf, color="#c63b3b", lw=1, ls=(0, (3, 2)))
    a.text(0.4, zf + 0.5, f"seuil d'affichage {nombre(zf, 0)} m", color="#c63b3b", fontsize=8)
    a.set_xlim(0, 20); a.set_ylim(-2, 22)
    a.set_xlabel("profondeur NONNA-100 (m)"); a.set_ylabel("profondeur Sentinel-2 hors pli (m)")
    a.set_title(f"{meilleur}, validation par blocs", fontsize=9.5)
    a = fig.add_subplot(gs[2, :2])
    classes = list(cl.classe.unique())
    x = np.arange(len(classes))
    w = 0.26
    teintes = {"Stumpf bleu/vert": "#3987e5", "Lyzenga 3 bandes": "#9ec5f4", "Forêt aléatoire": "#184f95"}
    for i, (mname, c) in enumerate(teintes.items()):
        v = cl[cl.modele == mname].set_index("classe").reindex(classes)
        a.bar(x + (i - 1) * w, v.eam, width=w - 0.03, color=c, label=mname)
    a.set_xticks(x); a.set_xticklabels([c.replace("-", " à ") for c in classes])
    a.set_ylabel("erreur absolue moyenne (m)"); a.yaxis.set_major_formatter(virgule(1))
    a.legend(fontsize=8, loc="upper left", ncol=3); a.grid(axis="x", visible=False)
    a.set_title("Erreur par classe de profondeur (cellules de 100 m hors pli, 5 plis par blocs de 1,5 km)")
    a = fig.add_subplot(gs[2, 2]); a.axis("off")
    lignes = []
    for _, r in sc.iterrows():
        lignes.append([r.modele, nombre(r.eam, 1), nombre(r.reqm, 1), nombre(r.biais, 1), nombre(r.r2, 2)])
    lignes.append(["carte affichée", nombre(li.carte_eam, 1), nombre(li.carte_reqm, 1),
                   nombre(li.carte_biais, 1), ""])
    t = a.table(cellText=lignes, colLabels=["", "EAM", "EQM", "biais", "R²"], loc="center",
                cellLoc="center", colLoc="center", colWidths=[0.44, 0.14, 0.14, 0.14, 0.14])
    t.auto_set_font_size(False); t.set_fontsize(8.2); t.scale(1, 1.55)
    for (i, j), c in t.get_celld().items():
        c.set_edgecolor(style.GRILLE)
        if j == 0:
            c.set_text_props(ha="left"); c._loc = "left"
        if i == 0:
            c.set_text_props(fontweight="semibold", color=style.ENCRE_2)
    a.set_title("Scores en mètres, 0 à 20 m", fontsize=9.5)
    fig.suptitle("Bathymétrie de la baie par satellite, confrontée aux sondages du SHC",
                 x=0.01, ha="left", fontsize=12, fontweight="semibold")
    fig.text(0.01, 0.015, f"Médiane de {int(li.n_scenes)} passages Sentinel-2 d'été sans glace (2017-2025). "
             "NONNA : Service hydrographique du Canada, usage non destiné à la navigation. "
             "Profondeurs au zéro des cartes.", fontsize=7.5, color=style.MUET)
    style.enregistrer(fig, F / "05_bathymetrie.png")


# ---------------------------------------------------------------------------
def fig_glace_regime(annee=2020):
    g = grille.grille(40.0)
    b = pd.read_csv(R / "glace_regime_annees.csv")
    import importlib
    sys.path.insert(0, str(Path(__file__).parent))
    m = importlib.import_module("06_glace_ancree")
    pente = m.pente_incidence()
    av, _ = m.composite(sorted(m.DOSSIER.glob(f"{annee}-04-*.tif")), pente)
    de, _ = m.composite([f for f in sorted(m.DOSSIER.glob(f"{annee - 1}-1[12]-*.tif"))
                         if config.S1_DEBUT_HIVER[0] <= f.stem[5:10] <= config.S1_DEBUT_HIVER[1]], pente)
    ids = grille.lire(config.DATA / "zone" / "masques_40m.tif", 3)
    delta = np.where(ids > 0, av - de, np.nan)
    fond = np.where(ids > 0, np.nan, av)
    fig, axs = plt.subplots(1, 2, figsize=(12, 5.2), gridspec_kw=dict(width_ratios=[1.15, 1], wspace=0.25))
    a = axs[0]
    a.imshow(fond, extent=g.etendue, cmap="Greys_r", vmin=-22, vmax=-4)
    cm = LinearSegmentedColormap.from_list("div", style.DIVERGENT)
    h = a.imshow(delta, extent=g.etendue, cmap=cm, vmin=-6, vmax=6, interpolation="nearest")
    a.set_xlim(490000, 522000); a.set_ylim(7664000, 7692000); axes_km(a)
    cb = fig.colorbar(h, ax=a, fraction=0.04); cb.set_label("σ⁰ avril moins décembre (dB)")
    cb.ax.yaxis.set_major_formatter(virgule(0))
    a.set_title(f"Lacs : changement du radar pendant l'hiver {annee - 1}-{annee}")
    a = axs[1]
    a.plot(b.annee, b.lacs_decembre_db, "o-", color="#9ec5f4", label="lacs, mi-nov. à mi-déc.")
    a.plot(b.annee, b.lacs_avril_db, "o-", color="#184f95", label="lacs, avril")
    a.plot(b.annee, b.lacs_avril_db - b.lacs_delta_db + b.terre_delta_db - b.terre_delta_db, alpha=0)
    a.yaxis.set_major_formatter(virgule(0)); a.set_ylabel("σ⁰ HH médian à 35° (dB)")
    for _, r in b.iterrows():
        a.annotate(f"{nombre(r.glace_stefan_30_avril_m, 2)} m", (r.annee, r.lacs_avril_db), xytext=(0, 7),
                   textcoords="offset points", ha="center", fontsize=7.5, color=style.ENCRE_2)
    a.legend(fontsize=8, loc="lower right")
    a.set_title("Le niveau de décembre varie plus que le signal recherché")
    a.set_xticks(b.annee)
    fig.text(0.01, -0.02, "Étiquettes : épaisseur de glace de Stefan au 30 avril. Rouge : la glace s'éclaircit "
             "(flottante) ; bleu : elle s'assombrit (glace posée sur le fond, ou artefact). Terre ferme : "
             "écart inférieur à 0,8 dB toutes les années.", fontsize=7.5, color=style.MUET)
    style.enregistrer(fig, F / "06_glace_regime.png")


FIGURES = {"zone": fig_zone, "series": fig_series_greiner, "angles": fig_angles_morts,
           "calendrier": fig_calendrier, "bathy": fig_bathy, "glace": fig_glace_regime}

if __name__ == "__main__":
    noms = sys.argv[1:] or list(FIGURES)
    for n in noms:
        FIGURES[n]()
        print("figure", n)
