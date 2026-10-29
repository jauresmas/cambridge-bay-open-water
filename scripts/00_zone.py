"""00. Zone d'étude : lacs OSM nommés, masque de la mer, rasters de lacs.

Sorties
- data/zone/lacs.gpkg : tous les lacs entièrement dans l'emprise (UTM 13 N)
- data/zone/masques_{80,40}m.tif : bande 1 identifiant du lac (contour érodé),
  bande 2 mer (1), bande 3 identifiant du lac sans érosion
- resultats/lacs.csv : lacs retenus pour les séries (surface >= 1 km2)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np

from cbow import config, grille, s2, zone

DOSSIER = config.DATA / "zone"

# Passages d'été sans nuage ni glace, choisis à la main dans le catalogue,
# pour le masque d'eau libre qui sépare la mer des terres.
PASSAGES_ETE = [
    ("S2A_MSIL2A_20240807T190911_R056_T13WDS_20240808T021150",
     "S2A_MSIL2A_20240807T190911_R056_T13WES_20240808T021150"),
    ("S2B_MSIL2A_20240816T184919_R113_T13WDS_20240816T230724",
     "S2B_MSIL2A_20240816T184919_R113_T13WES_20240816T230724"),
]


def scene(id_):
    from cbow import stac
    return stac._requete(
        "GET", f"{config.STAC_PC}/collections/{s2.COLLECTION}/items/{id_}").json()


def eau_ete(g):
    """Eau libre d'été : proche infrarouge sombre et vert plus fort que lui.

    Le NDWI n'est pas utilisable ici : la correction atmosphérique L2A donne
    des réflectances légèrement négatives sur l'eau sombre.
    """
    votes = []
    for ids in PASSAGES_ETE:
        b = s2.lire_bandes([scene(i) for i in ids], g, bandes=("B03", "B8A"))
        votes.append((b["B8A"] < 0.04) & (b["B03"] > b["B8A"]))
    return np.mean(np.stack(votes), axis=0) >= 0.5


def main():
    DOSSIER.mkdir(parents=True, exist_ok=True)
    js = zone.telecharger_eau_osm(DOSSIER / "osm_eau.json")
    lacs = zone.lacs_projetes(zone.polygones_osm(js))
    topo = zone.telecharger_toponymes(DOSSIER / "toponymes.json")
    lacs = zone.nommer_lacs(lacs, topo)
    lacs[["lac_id", "osm_id", "nom", "surface_km2", "geometry"]].to_file(
        DOSSIER / "lacs.gpkg", layer="lacs", driver="GPKG")
    print(f"{len(lacs)} plans d'eau entiers dans l'emprise, "
          f"{(lacs.surface_km2 >= config.LAC_SURFACE_MIN_KM2).sum()} de plus de "
          f"{config.LAC_SURFACE_MIN_KM2:g} km2")

    retenus = lacs[lacs.surface_km2 >= config.LAC_SURFACE_MIN_KM2]
    for res in (config.RES_S1_SERIE, config.RES_S1_CARTE):
        g = grille.grille(res)
        ids_erodes = zone.raster_ids(retenus, g, config.LAC_EROSION_M)
        ids_bruts = zone.raster_ids(lacs, g, 0.0)
        mer = zone.masque_mer(eau_ete(g), ids_bruts, g)
        grille.ecrire(DOSSIER / f"masques_{int(res)}m.tif",
                      np.stack([ids_erodes, mer.astype("int32"), ids_bruts]), g)
        print(f"  grille {res:g} m : {np.unique(ids_erodes).size - 1} lacs, "
              f"mer {mer.sum() * res * res / 1e6:.0f} km2")

    g = grille.grille(config.RES_S1_SERIE)
    ids = grille.lire(DOSSIER / f"masques_{int(g.res)}m.tif")
    n_pix = np.bincount(ids.ravel(), minlength=lacs.lac_id.max() + 1)
    tab = retenus.drop(columns="geometry").copy()
    tab["pixels_80m"] = n_pix[tab.lac_id]
    c = retenus.geometry.centroid.to_crs("EPSG:4326")
    tab["lon"], tab["lat"] = c.x.round(5), c.y.round(5)
    tab = tab[tab.pixels_80m >= 30]
    config.RESULTATS.mkdir(exist_ok=True)
    tab.to_csv(config.RESULTATS / "lacs.csv", index=False, float_format="%.3f")
    print(tab.head(15).to_string(index=False))


if __name__ == "__main__":
    main()
