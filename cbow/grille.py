"""Grilles de travail communes et lecture des COG sur ces grilles."""
from __future__ import annotations

import os

os.environ.pop("PROJ_LIB", None)  # la base PROJ de PostGIS du poste est trop ancienne

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.transform import from_origin
from rasterio.vrt import WarpedVRT

from . import config


@dataclass(frozen=True)
class Grille:
    xmin: float
    ymin: float
    xmax: float
    ymax: float
    res: float
    crs: str = config.CRS

    @property
    def largeur(self) -> int:
        return int(round((self.xmax - self.xmin) / self.res))

    @property
    def hauteur(self) -> int:
        return int(round((self.ymax - self.ymin) / self.res))

    @property
    def forme(self) -> tuple[int, int]:
        return self.hauteur, self.largeur

    @property
    def transform(self):
        return from_origin(self.xmin, self.ymax, self.res, self.res)

    @property
    def etendue(self) -> list[float]:
        """Pour matplotlib (imshow extent)."""
        return [self.xmin, self.xmax, self.ymin, self.ymax]

    def centres(self) -> tuple[np.ndarray, np.ndarray]:
        xs = self.xmin + (np.arange(self.largeur) + 0.5) * self.res
        ys = self.ymax - (np.arange(self.hauteur) + 0.5) * self.res
        return np.meshgrid(xs, ys)


def grille(res: float, emprise=config.EMPRISE) -> Grille:
    return Grille(*emprise, res=res)


def lire_sur_grille(href: str, g: Grille, resampling=Resampling.average,
                    nodata=0, dtype="float32") -> np.ndarray:
    """Lit la première bande d'un raster distant, reprojetée sur la grille.

    GDAL choisit l'aperçu (overview) le plus proche de la résolution demandée,
    ce qui limite le volume téléchargé.
    """
    with rasterio.open(href) as src, WarpedVRT(
        src, crs=g.crs, transform=g.transform, width=g.largeur, height=g.hauteur,
        resampling=resampling, src_nodata=nodata, nodata=nodata,
    ) as vrt:
        return vrt.read(1).astype(dtype)


def ecrire(chemin: Path, tableau: np.ndarray, g: Grille, nodata=None, **profil):
    chemin.parent.mkdir(parents=True, exist_ok=True)
    tableau = np.asarray(tableau)
    if tableau.ndim == 2:
        tableau = tableau[None]
    prof = dict(driver="GTiff", height=g.hauteur, width=g.largeur,
                count=tableau.shape[0], dtype=tableau.dtype, crs=g.crs,
                transform=g.transform, compress="deflate", tiled=True,
                blockxsize=256, blockysize=256, nodata=nodata)
    if tableau.dtype.kind == "f":
        prof["predictor"] = 3
    elif tableau.dtype.kind in "iu" and tableau.dtype.itemsize > 1:
        prof["predictor"] = 2
    prof.update(profil)
    with rasterio.open(chemin, "w", **prof) as dst:
        dst.write(tableau)


def lire(chemin: Path, bande: int = 1) -> np.ndarray:
    with rasterio.open(chemin) as src:
        return src.read(bande)
