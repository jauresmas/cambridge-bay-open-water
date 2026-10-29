"""10. Couches du projet QGIS (resultats/qgis/), publiées avec le dépôt.

- cambridge_bay.gpkg :
  lacs_suivis        les lacs suivis et leurs dates médianes (2017-2025)
  lacs_suivis_erodes les mêmes, érodés de 120 m (contrôle croisé du modèle QGIS)
  eau_libre_lac_annee un polygone par lac et par année, de la débâcle à la prise
                     (champs date pour le contrôleur temporel de QGIS)
  mer, hameau, cadre_bathymetrie
- fond_sentinel2_ete_40m.tif : fond couleur 8 bits du 7 août 2024
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from rasterio import features
from shapely.geometry import Point, box, shape

from cbow import config, grille

SORTIE = config.RESULTATS / "qgis"


def date(doy, an=2021):
    if pd.isna(doy):
        return None
    return (pd.Timestamp(f"{an}-01-01") + pd.Timedelta(days=round(doy) - 1)).strftime("%Y-%m-%d")


def main():
    SORTIE.mkdir(parents=True, exist_ok=True)
    gpkg = SORTIE / "cambridge_bay.gpkg"
    if gpkg.exists():
        gpkg.unlink()
    lacs = gpd.read_file(config.DATA / "zone" / "lacs.gpkg")
    retenus = pd.read_csv(config.RESULTATS / "lacs.csv")
    fen = pd.read_csv(config.RESULTATS / "fenetre_eau_libre.csv")
    fen = fen[fen.objet.astype(str) != "mer"].copy()
    fen["lac_id"] = fen.objet.astype(int)

    med = fen.groupby("lac_id").agg(
        fonte_jour=("jour_fonte", "median"), debacle_jour=("jour_debacle", "median"),
        prise_jour=("jour_prise", "median"), eau_libre_j=("eau_libre_j", "median"),
        annees=("eau_libre_j", "count")).reset_index()
    for c in ("fonte", "debacle", "prise"):
        med[f"{c}_mediane"] = med[f"{c}_jour"].map(date)
    suivis = lacs[lacs.lac_id.isin(retenus.lac_id)].merge(med, on="lac_id", how="left")
    suivis["nom"] = suivis["nom"].fillna("")
    suivis.to_file(gpkg, layer="lacs_suivis", driver="GPKG")
    erodes = suivis[["lac_id", "nom", "geometry"]].copy()
    erodes["geometry"] = erodes.buffer(-config.LAC_EROSION_M)
    erodes[~erodes.is_empty].to_file(gpkg, layer="lacs_suivis_erodes", driver="GPKG")

    lignes = []
    for _, r in fen.dropna(subset=["debacle", "prise"]).iterrows():
        lignes.append(dict(lac_id=int(r.lac_id), annee=int(r.annee), debacle=pd.Timestamp(r.debacle).normalize(),
                           prise=pd.Timestamp(r.prise).normalize(), eau_libre_j=float(r.eau_libre_j)))
    la = pd.DataFrame(lignes).merge(suivis[["lac_id", "nom", "geometry"]], on="lac_id")
    gpd.GeoDataFrame(la, geometry="geometry", crs=suivis.crs).to_file(gpkg, layer="eau_libre_lac_annee",
                                                                         driver="GPKG")

    g = grille.grille(40.0)
    mer = grille.lire(config.DATA / "zone" / "masques_40m.tif", 2).astype("uint8")
    polys = [shape(geo) for geo, v in features.shapes(mer, mask=mer == 1, transform=g.transform) if v == 1]
    gpd.GeoDataFrame(dict(nom=["baie et détroit de Dease"] * len(polys)), geometry=polys, crs=config.CRS) \
        .dissolve().to_file(gpkg, layer="mer", driver="GPKG")
    from pyproj import Transformer
    hx, hy = Transformer.from_crs(4326, config.CRS, always_xy=True).transform(*config.HAMEAU)
    gpd.GeoDataFrame(dict(nom=["Cambridge Bay (Iqaluktuuttiaq)"]), geometry=[Point(hx, hy)], crs=config.CRS) \
        .to_file(gpkg, layer="hameau", driver="GPKG")
    gpd.GeoDataFrame(dict(nom=["zone de bathymétrie"]), geometry=[box(*config.EMPRISE_BAIE)], crs=config.CRS) \
        .to_file(gpkg, layer="cadre_bathymetrie", driver="GPKG")

    # fond couleur : même étirement que les figures, en 8 bits et compression JPEG
    with rasterio.open(config.DATA / "zone" / "rgb_ete_40m.tif") as src:
        a = src.read()
        prof = src.profile
    rgb = np.clip((a - 0.005) / 0.16, 0, 1) ** 0.8
    # hors image : blanc ; pas de valeur « sans donnée », que la compression JPEG ferait
    # apparaître en taches sur l'eau sombre
    rgb = np.where(np.isfinite(rgb), np.round(rgb * 255), 255).astype("uint8")
    prof.update(dtype="uint8", nodata=None, compress="jpeg", photometric="ycbcr", jpeg_quality=88,
                tiled=True, blockxsize=256, blockysize=256, predictor=None)
    prof.pop("predictor", None)
    with rasterio.open(SORTIE / "fond_sentinel2_ete_40m.tif", "w", **prof) as dst:
        dst.write(rgb)
    print(f"{len(suivis)} lacs suivis, {len(la)} couples lac-année, couches dans {SORTIE}")


if __name__ == "__main__":
    main()
