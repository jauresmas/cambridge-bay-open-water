"""07. Étapes de la débâcle et de la prise des glaces, par capteur, puis fusion.

La débâcle et la prise ne sont pas des dates mais des processus, et chaque
capteur en voit une étape :

débâcle
- « eau en surface » (thermique Landsat) : toute la surface dépasse 2 °C ;
  sur un lac encore gelé, c'est l'eau de fonte qui recouvre la glace ;
- « fonte » (radar Sentinel-1) : neige humide sur la glace ;
- « débâcle » (optique Sentinel-2) : l'eau libre couvre 90 % du lac ;
prise
- « première glace » (thermique) : toute la surface passe sous -1 °C ;
- « prise » (radar et optique) : glace consolidée, régulière au radar,
  enneigée en optique (90 % du lac).

Fusion : quand deux capteurs encadrent la même étape (la prise, vue par le
radar et l'optique), la date est dans l'intersection de leurs intervalles.
Si les intervalles ne se recoupent pas, l'événement est discordant et on
garde l'intervalle le plus étroit.

Sorties (resultats/)
- s1_pentes_incidence.csv, phenologie_capteurs.csv, phenologie_fusion.csv,
  phenologie_concordance.csv, angles_morts.csv, fenetre_eau_libre.csv,
  s1_prise_variantes.csv (sensibilité du critère radar)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
import pandas as pd

from cbow import config, phenologie as ph

R = config.RESULTATS
# étape -> capteurs qui la voient (seuls ceux-là sont fusionnés)
ETAPES = {"eau_surface": ["Landsat TIRS"], "fonte": ["Sentinel-1"], "debacle": ["Sentinel-2"],
          "premiere_glace": ["Landsat TIRS"], "prise": ["Sentinel-1", "Sentinel-2"]}


def charger():
    s2 = pd.read_csv(R / "s2_lacs.csv", parse_dates=["date"])
    s2 = s2[s2.part_claire >= config.FRACTION_VALIDE_MIN]
    # deux passages le même jour : on garde le plus clair
    s2 = s2.sort_values("part_claire").drop_duplicates(["date", "objet"], keep="last")
    s1 = pd.read_csv(R / "s1_lacs.csv", parse_dates=["date"])
    s1 = s1.sort_values("n").drop_duplicates(["date", "objet", "orbite"], keep="last")
    ls = pd.read_csv(R / "landsat_lacs.csv", parse_dates=["date"])
    ls = ls.sort_values("part_claire").drop_duplicates(["date", "objet"], keep="last")
    for t in (s2, s1, ls):
        t["objet"] = t["objet"].astype(str)
    return s2, s1, ls


def ligne(objet, an, capteur, evenement, t: ph.Transition):
    return dict(objet=objet, annee=an, capteur=capteur, evenement=evenement,
                avant=t.avant, apres=t.apres, date=t.date, demi_largeur_j=t.demi_largeur,
                n_obs=t.n_obs)


def par_capteur(s2, s1, ls):
    tair = pd.read_csv(R / "meteo_quotidienne.csv", parse_dates=["date"]).set_index("date")["tair"]
    lignes, pentes = [], []
    objets = sorted((set(s2.objet) | set(s1.objet) | set(ls.objet)) - {"terre"})
    for o in objets:
        o2, o1, ol = s2[s2.objet == o], s1[s1.objet == o].copy(), ls[ls.objet == o]
        if len(o1) > 20:
            o1["db_norm"], pente = ph.normaliser_incidence(o1)
            pentes.append(dict(objet=o, pente=pente))
        for an in config.ANNEES:
            if len(o2):
                lignes.append(ligne(o, an, "Sentinel-2", "debacle", ph.debacle_s2(o2, an)))
                lignes.append(ligne(o, an, "Sentinel-2", "prise", ph.prise_s2(o2, an)))
            if len(ol):
                lignes.append(ligne(o, an, "Landsat TIRS", "eau_surface", ph.debacle_thermique(ol, an)))
                lignes.append(ligne(o, an, "Landsat TIRS", "premiere_glace", ph.prise_thermique(ol, an)))
            if "db_norm" in o1:
                lignes.append(ligne(o, an, "Sentinel-1", "fonte", ph.fonte_s1(o1, an, tair=tair)))
                lignes.append(ligne(o, an, "Sentinel-1", "prise", ph.prise_s1(o1, an)))
    return pd.DataFrame(lignes), pd.DataFrame(pentes)


def fusion(cap: pd.DataFrame) -> pd.DataFrame:
    lignes = []
    ok = cap.dropna(subset=["date"])
    for (o, an, ev), g in ok.groupby(["objet", "annee", "evenement"]):
        g = g[g.capteur.isin(ETAPES[ev])]
        if g.empty:
            continue
        debut, fin = g.avant.max(), g.apres.min()
        if debut <= fin:
            etat = "concordant" if len(g) > 1 else "un seul capteur"
            date = debut + (fin - debut) / 2
            demi = (fin - debut).days / 2
        else:
            etat = "discordant"
            meilleur = g.sort_values("demi_largeur_j").iloc[0]
            date, demi = meilleur.date, meilleur.demi_largeur_j
        lignes.append(dict(objet=o, annee=an, evenement=ev, date=date, demi_largeur_j=demi,
                           capteurs=" + ".join(sorted(g.capteur)), etat=etat))
    return pd.DataFrame(lignes)


def concordance(cap: pd.DataFrame, fus: pd.DataFrame) -> pd.DataFrame:
    """Écart (jours) entre deux étapes ou deux capteurs, pour le même lac et la même année.

    Écart = date de A moins date de B : positif, A vient après B.
    """
    ok = cap.dropna(subset=["date"])
    piv = ok.pivot_table(index=["objet", "annee"], columns=["evenement", "capteur"],
                         values="date", aggfunc="first")
    fpiv = fus.pivot_table(index=["objet", "annee"], columns="evenement", values="date", aggfunc="first")
    paires = [
        ("prise, radar et optique", piv.get(("prise", "Sentinel-2")), piv.get(("prise", "Sentinel-1"))),
        ("débâcle optique après l'eau en surface (thermique)", piv.get(("debacle", "Sentinel-2")),
         piv.get(("eau_surface", "Landsat TIRS"))),
        ("débâcle optique après la fonte (radar)", piv.get(("debacle", "Sentinel-2")),
         piv.get(("fonte", "Sentinel-1"))),
        ("prise consolidée après la première glace (thermique)", fpiv.get("prise"),
         piv.get(("premiere_glace", "Landsat TIRS"))),
    ]
    lignes = []
    for nom, a, b in paires:
        if a is None or b is None:
            continue
        d = (pd.to_datetime(a) - pd.to_datetime(b)).dt.days.dropna()
        lignes.append(dict(comparaison=nom, n=len(d), ecart_median_j=d.median(),
                           ecart_absolu_median_j=d.abs().median(),
                           ecart_q1_j=d.quantile(0.25), ecart_q3_j=d.quantile(0.75),
                           part_moins_7j=(d.abs() <= 7).mean() if len(d) else np.nan))
    return pd.DataFrame(lignes)


def angles_morts(cap: pd.DataFrame, fus: pd.DataFrame) -> pd.DataFrame:
    lignes = []
    for (c, ev), g in cap.groupby(["capteur", "evenement"]):
        lignes.append(dict(capteur=c, evenement=ev, cas=len(g),
                           part_datee=g.date.notna().mean(),
                           demi_largeur_mediane_j=g.demi_largeur_j.median(),
                           demi_largeur_p90_j=g.demi_largeur_j.quantile(0.9)))
    g = fus[fus.evenement == "prise"]
    lignes.append(dict(capteur="fusion", evenement="prise", cas=len(g), part_datee=np.nan,
                       demi_largeur_mediane_j=g.demi_largeur_j.median(),
                       demi_largeur_p90_j=g.demi_largeur_j.quantile(0.9)))
    return pd.DataFrame(lignes)


def fenetre(fus: pd.DataFrame) -> pd.DataFrame:
    d = fus.pivot_table(index=["objet", "annee"], columns="evenement", values="date", aggfunc="first")
    d = d.reset_index()
    for c in ETAPES:
        if c not in d:
            d[c] = pd.NaT
        d[f"jour_{c}"] = pd.to_datetime(d[c]).dt.dayofyear
    d["eau_libre_j"] = (pd.to_datetime(d.prise) - pd.to_datetime(d.debacle)).dt.days
    d["fonte_a_debacle_j"] = (pd.to_datetime(d.debacle) - pd.to_datetime(d.fonte)).dt.days
    return d


def variantes_prise_radar(s1: pd.DataFrame, cap: pd.DataFrame) -> pd.DataFrame:
    """Sensibilité du seuil de dispersion radar, jugée sur la prise optique.

    Le seuil de 1,2 dB est celui de la méthode ; les autres valeurs montrent
    s'il est un choix favorable ou robuste, séparément sur 2017-2020 et
    2021-2025 (moins de passages radar après la perte de Sentinel-1B).
    """
    pentes = pd.read_csv(R / "s1_pentes_incidence.csv", dtype={"objet": str})
    p = dict(zip(pentes.objet, pentes.pente))
    s1 = s1[s1.objet != "mer"].copy()
    s1["db_norm"] = s1.db_med - s1.objet.map(p) * (s1.incidence - 35)
    ref = cap[(cap.capteur == "Sentinel-2") & (cap.evenement == "prise")].set_index(["objet", "annee"]).date
    lignes = []
    for seuil in (0.8, 1.0, 1.2, 1.6, 2.0):
        for (o, an), g in s1.groupby(["objet", s1.date.dt.year]):
            d = ph.prise_s1(g, an, seuil_dispersion=seuil).date
            r = ref.get((o, an))
            if d is not None and pd.notna(r):
                lignes.append(dict(seuil_db=seuil, periode="2017-2020" if an <= 2020 else "2021-2025",
                                   ecart_j=(d - r).days))
    t = pd.DataFrame(lignes)
    return t.groupby(["seuil_db", "periode"]).ecart_j.agg(
        n="count", biais_median_j="median", ecart_absolu_median_j=lambda x: x.abs().median()).reset_index()


def main():
    s2, s1, ls = charger()
    cap, pentes = par_capteur(s2, s1, ls)
    pentes.to_csv(R / "s1_pentes_incidence.csv", index=False, float_format="%.4f")
    cap.to_csv(R / "phenologie_capteurs.csv", index=False, date_format="%Y-%m-%d")
    fus = fusion(cap)
    fus.to_csv(R / "phenologie_fusion.csv", index=False, date_format="%Y-%m-%d")
    conc = concordance(cap, fus)
    conc.to_csv(R / "phenologie_concordance.csv", index=False, float_format="%.2f")
    am = angles_morts(cap, fus)
    am.to_csv(R / "angles_morts.csv", index=False, float_format="%.2f")
    fen = fenetre(fus)
    fen.to_csv(R / "fenetre_eau_libre.csv", index=False, date_format="%Y-%m-%d")
    var = variantes_prise_radar(s1, cap)
    var.to_csv(R / "s1_prise_variantes.csv", index=False, float_format="%.1f")
    print(f"pente d'incidence médiane : {pentes.pente.median():.3f} dB/deg")
    print(conc.to_string(index=False))
    print(am.to_string(index=False))
    print(fus[fus.evenement == "prise"].etat.value_counts().to_string())
    print(var.to_string(index=False))
    lacs = fen[fen.objet != "mer"]
    cols = [f"jour_{c}" for c in ETAPES] + ["eau_libre_j"]
    print("lacs, médianes par année :")
    print(lacs.groupby("annee")[cols].median().to_string())
    print("mer :")
    print(fen[fen.objet == "mer"][["annee", "fonte", "debacle", "prise", "eau_libre_j"]].to_string(index=False))


if __name__ == "__main__":
    main()
