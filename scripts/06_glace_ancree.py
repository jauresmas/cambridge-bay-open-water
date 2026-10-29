"""06. Régime de la glace des lacs en fin d'hiver (exploratoire).

Sous la glace flottante, l'interface glace-eau renvoie fortement le signal
radar et le sigma0 croît pendant l'hiver, à mesure que la glace s'épaissit.
Quand la glace touche le fond, ce contraste disparaît et le sigma0 baisse.
On compare donc, pixel par pixel, la médiane d'avril (fin d'hiver) à celle
de mi-novembre à mi-décembre (début d'hiver), à incidence normalisée :

- hausse d'au moins 1,5 dB : glace flottante ;
- baisse d'au moins 1,5 dB : glace probablement posée sur le fond ;
- entre les deux : indéterminé (pixels mêlés, glace posée dès décembre).

L'épaisseur de glace de Stefan au 30 avril donne la profondeur que la glace
atteint : la part de glace posée devrait croître avec cette épaisseur. C'est
l'hypothèse testée, sans mesure de terrain ici. La terre ferme sert de
témoin : son sigma0 ne doit pas changer entre décembre et avril.

Sorties
- resultats/glace_regime_AAAA_40m.tif (1 flottante, 2 posée, 3 indéterminé)
- resultats/glace_regime_lacs.csv : par année et par lac, parts de chaque
  régime ; resultats/glace_regime_annees.csv : bilan annuel et Stefan
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
import pandas as pd
import rasterio
from scipy import ndimage

from cbow import config, grille

DOSSIER = config.DATA / "s1" / "cartes_40m"
SEUIL_DB = 1.5


def pente_incidence() -> float:
    """Pente moyenne des lacs (dB par degré), estimée dans 07_phenologie."""
    f = config.RESULTATS / "s1_pentes_incidence.csv"
    if f.exists():
        return float(pd.read_csv(f)["pente"].median())
    return -0.23


def composite(fichiers, pente) -> tuple[np.ndarray, int]:
    pile = []
    for f in fichiers:
        with rasterio.open(f) as s:
            v = s.read(1).astype("float32")
            inc = float(s.tags()["incidence"])
        v[v == -32768] = np.nan
        pile.append(v / 100 - pente * (inc - 35))
    if not pile:
        return None, 0
    with np.errstate(invalid="ignore"):
        return np.nanmedian(np.stack(pile), axis=0), len(pile)


def main():
    g = grille.grille(config.RES_S1_CARTE)
    pente = pente_incidence()
    ids = grille.lire(config.DATA / "zone" / "masques_40m.tif", 3)
    # un pixel retiré le long des rives (résolution EW d'environ 90 m)
    lac = ndimage.binary_erosion(ids > 0, iterations=1)
    mer = grille.lire(config.DATA / "zone" / "masques_40m.tif", 2) == 1
    terre = ndimage.binary_erosion((ids == 0) & ~mer, iterations=3)
    lacs = pd.read_csv(config.RESULTATS / "lacs.csv")
    an_meteo = pd.read_csv(config.RESULTATS / "meteo_annuelle.csv")
    lignes, bilans = [], []
    for an in config.ANNEES[1:]:
        avril, n_a = composite(sorted(DOSSIER.glob(f"{an}-04-*.tif")), pente)
        debut = [f for f in sorted(DOSSIER.glob(f"{an - 1}-1[12]-*.tif"))
                 if config.S1_DEBUT_HIVER[0] <= f.stem[5:10] <= config.S1_DEBUT_HIVER[1]]
        dec, n_d = composite(debut, pente)
        if avril is None or dec is None:
            continue
        delta = avril - dec
        regime = np.zeros(g.forme, "uint8")
        ok = lac & np.isfinite(delta)
        regime[ok] = 3
        regime[ok & (delta >= SEUIL_DB)] = 1
        regime[ok & (delta <= -SEUIL_DB)] = 2
        grille.ecrire(config.RESULTATS / f"glace_regime_{an}_40m.tif", regime, g, nodata=0)
        for lid in lacs.lac_id:
            m = ok & (ids == lid)
            if m.sum() < 20:
                continue
            r = regime[m]
            lignes.append(dict(annee=an, lac_id=lid, pixels=int(m.sum()),
                               flottante=(r == 1).mean(), posee=(r == 2).mean(),
                               indeterminee=(r == 3).mean(),
                               delta_median_db=float(np.median(delta[m]))))
        r = regime[ok]
        st = an_meteo[an_meteo.annee_glace == an].iloc[0]
        bilans.append(dict(annee=an, passages_avril=n_a, passages_decembre=n_d,
                           lacs_decembre_db=float(np.nanmedian(dec[lac])),
                           lacs_avril_db=float(np.nanmedian(avril[lac])),
                           terre_delta_db=float(np.nanmedian(delta[terre])),
                           lacs_delta_db=float(np.nanmedian(delta[lac])),
                           flottante=(r == 1).mean(), posee=(r == 2).mean(),
                           indeterminee=(r == 3).mean(),
                           glace_stefan_30_avril_m=st.glace_stefan_30_avril_m,
                           djg_30_avril=st.djg_30_avril))
    pd.DataFrame(lignes).to_csv(config.RESULTATS / "glace_regime_lacs.csv", index=False, float_format="%.4f")
    b = pd.DataFrame(bilans)
    b.to_csv(config.RESULTATS / "glace_regime_annees.csv", index=False, float_format="%.4f")
    print(f"pente d'incidence {pente:.3f} dB/deg")
    print(b.to_string(index=False))
    if len(b) > 3:
        r = np.corrcoef(b.glace_stefan_30_avril_m, b.posee)[0, 1]
        r_dec = np.corrcoef(b.lacs_decembre_db, b.posee)[0, 1]
        print(f"corrélation part posée / épaisseur de Stefan : r = {r:.2f} (n = {len(b)})")
        print(f"corrélation part posée / niveau des lacs en décembre : r = {r_dec:.2f}")


if __name__ == "__main__":
    main()
