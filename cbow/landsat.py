"""Landsat 8 et 9, collection 2 niveau 2 : température de surface (bande 10)."""
from __future__ import annotations

import numpy as np
import rasterio
from rasterio.enums import Resampling

from . import stac
from .grille import Grille, lire_sur_grille

COLLECTION = "landsat-c2-l2"
ECHELLE_ST, DECALAGE_ST = 0.00341802, 149.0   # kelvins
# bits de QA_PIXEL à exclure : remplissage, nuage dilaté, cirrus, nuage, ombre
BITS_EXCLUS = (0, 1, 2, 3, 4)
INCERTITUDE_MAX_K = 3.0
DISTANCE_NUAGE_MIN_KM = 1.0


def chercher(debut: str, fin: str, cache=None) -> list[dict]:
    return stac.chercher(COLLECTION, debut, fin, cache=cache, requete={
        "eo:cloud_cover": {"lt": 70}, "platform": {"in": ["landsat-8", "landsat-9"]}})


def masque_qa(qa: np.ndarray) -> np.ndarray:
    """Vrai pour les pixels clairs (aucun bit exclu levé)."""
    q = qa.astype("uint16")
    mauvais = np.zeros(q.shape, bool)
    for b in BITS_EXCLUS:
        mauvais |= (q >> b) & 1 == 1
    return (q > 0) & ~mauvais


def temperature_sur_grille(scene: dict, g: Grille) -> np.ndarray:
    """Température de surface (°C) des pixels clairs, NaN ailleurs."""
    a = scene["assets"]
    with rasterio.Env(**stac.ENV_GDAL):
        st = lire_sur_grille(stac.signer(a["lwir11"]["href"], COLLECTION), g)
        qa = lire_sur_grille(stac.signer(a["qa_pixel"]["href"], COLLECTION), g,
                             resampling=Resampling.nearest, nodata=1, dtype="uint16")
        inc = lire_sur_grille(stac.signer(a["qa"]["href"], COLLECTION), g, nodata=-9999)
        dist = lire_sur_grille(stac.signer(a["cdist"]["href"], COLLECTION), g, nodata=-9999)
    t = st * ECHELLE_ST + DECALAGE_ST - 273.15
    ok = ((st > 0) & masque_qa(qa) & (inc > 0) & (inc * 0.01 <= INCERTITUDE_MAX_K)
          & (dist * 0.01 >= DISTANCE_NUAGE_MIN_KM))
    return np.where(ok, t, np.nan).astype("float32")
