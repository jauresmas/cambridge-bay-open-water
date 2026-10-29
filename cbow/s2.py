"""Sentinel-2 L2A : lecture par acquisition et classes eau, glace, nuage."""
from __future__ import annotations

import os

os.environ.pop("PROJ_LIB", None)

from collections import defaultdict

import numpy as np
import rasterio
from rasterio.enums import Resampling

from . import config, stac
from .grille import Grille, lire_sur_grille

COLLECTION = "sentinel-2-l2a"
TUILES = ("13WDS", "13WES")

# Codes des classes par pixel
SANS_DONNEE, NUAGE, EAU, GLACE, AUTRE = 0, 1, 2, 3, 4
NOMS_CLASSES = {SANS_DONNEE: "sans donnée", NUAGE: "nuage", EAU: "eau libre",
                GLACE: "glace ou neige", AUTRE: "autre (sol, mélange)"}


def chercher(debut: str, fin: str, cache=None) -> list[dict]:
    req = {"eo:cloud_cover": {"lt": config.S2_NUAGES_MAX},
           "s2:mgrs_tile": {"in": list(TUILES)}}
    scenes = stac.chercher(COLLECTION, debut, fin, requete=req, cache=cache)
    return [s for s in scenes
            if s["properties"].get("s2:mean_solar_zenith", 90) <= config.S2_ZENITH_MAX]


def acquisitions(scenes: list[dict]) -> list[list[dict]]:
    """Regroupe les tuiles d'un même passage (date et orbite relative)."""
    groupes = defaultdict(list)
    for s in scenes:
        p = s["properties"]
        groupes[(p["datetime"][:10], p["sat:relative_orbit"])].append(s)
    return [sorted(v, key=lambda s: s["id"]) for _, v in sorted(groupes.items())]


def _decalage(scene: dict) -> float:
    base = scene["properties"].get("s2:processing_baseline", "00.00")
    return -1000.0 if float(base) >= 4.0 else 0.0


def lire_bandes(groupe: list[dict], g: Grille, bandes=("B03", "B11", "SCL")) -> dict:
    """Réflectances (0 à 1) des tuiles d'un passage, assemblées sur la grille."""
    sortie = {b: np.full(g.forme, np.nan, dtype="float32") for b in bandes}
    with rasterio.Env(**stac.ENV_GDAL):
        for s in groupe:
            dec = _decalage(s)
            for b in bandes:
                href = stac.signer(s["assets"][b]["href"], COLLECTION)
                rs = Resampling.nearest if b == "SCL" else Resampling.average
                a = lire_sur_grille(href, g, resampling=rs, nodata=0)
                ok = (a > 0) & np.isnan(sortie[b])
                if b == "SCL":
                    sortie[b][ok] = a[ok]
                else:
                    sortie[b][ok] = (a[ok] + dec) / 10000.0
    return sortie


def classer(vert: np.ndarray, swir: np.ndarray, scl: np.ndarray) -> np.ndarray:
    """Classe chaque pixel : nuage, eau libre, glace ou neige, autre.

    Règles (seuils dans config) :
    - nuage : classes SCL ombre, nuage moyen ou haut, cirrus, ou SWIR fort
      (la glace, la neige et l'eau absorbent toutes à 1,6 um) ;
    - eau libre : visible sombre, ou classe « eau » de Sen2Cor tant que le
      vert reste modéré (eau turbide ou voilée, fréquente après la débâcle) ;
    - glace ou neige : NDSI élevé et visible clair, hors de ce cas.
    Le reste (sol, végétation, glace très sale, pixels mêlés) est « autre ».
    """
    c = np.full(vert.shape, AUTRE, dtype="uint8")
    valide = np.isfinite(vert) & np.isfinite(swir) & np.isfinite(scl)
    with np.errstate(divide="ignore", invalid="ignore"):
        ndsi = (vert - swir) / (vert + swir)
    nuage = np.isin(scl, config.S2_SCL_NUAGES) | (swir > config.S2_SWIR_NUAGE)
    eau_scl = (scl == 6) & (vert < config.S2_VERT_EAU_SCL)
    glace = (ndsi > config.S2_NDSI_GLACE) & (vert > config.S2_VERT_GLACE) & ~eau_scl
    eau = ((vert < config.S2_VERT_EAU) | eau_scl) & ~glace
    c[eau] = EAU
    c[glace] = GLACE
    c[nuage] = NUAGE
    c[~valide] = SANS_DONNEE
    return c


def ndwi(vert: np.ndarray, pir: np.ndarray) -> np.ndarray:
    with np.errstate(divide="ignore", invalid="ignore"):
        return (vert - pir) / (vert + pir)
