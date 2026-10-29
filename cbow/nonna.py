"""Sondages du Service hydrographique du Canada (NONNA), par le WCS public.

NONNA (« non-navigational ») : profondeurs maillées à environ 10 m (NONNA-10)
et 100 m (NONNA-100), rapportées au zéro des cartes. Usage non destiné à la
navigation. Licence du gouvernement ouvert du Canada.
"""
from __future__ import annotations

import os

os.environ.pop("PROJ_LIB", None)

from pathlib import Path

import numpy as np
import rasterio
import requests
from pyproj import Transformer
from rasterio.enums import Resampling
from rasterio.warp import reproject

from .grille import Grille

WCS = "https://nonna-geoserver.data.chs-shc.ca/geoserver/wcs"
COUVERTURES = {10: "nonna__NONNA 10 Coverage", 100: "nonna__NONNA 100 Coverage"}


def telecharger(g: Grille, resolution: int, cache: Path, marge=2000.0) -> Path:
    """Extrait NONNA sur l'emprise de la grille (plus une marge), en EPSG:3857."""
    if cache.exists():
        return cache
    vers = Transformer.from_crs(g.crs, "EPSG:3857", always_xy=True)
    xs, ys = vers.transform([g.xmin - marge, g.xmax + marge, g.xmin - marge, g.xmax + marge],
                            [g.ymin - marge, g.ymin - marge, g.ymax + marge, g.ymax + marge])
    params = {"service": "WCS", "version": "2.0.1", "request": "GetCoverage",
              "coverageId": COUVERTURES[resolution], "format": "image/tiff"}
    url = (f"{WCS}?" + "&".join(f"{k}={v}" for k, v in params.items())
           + f"&subset=X({min(xs)},{max(xs)})&subset=Y({min(ys)},{max(ys)})")
    r = requests.get(url, timeout=900)
    r.raise_for_status()
    if not r.content.startswith((b"II*", b"MM\x00*")):
        raise RuntimeError(r.text[:300])
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_bytes(r.content)
    return cache


def profondeur_sur_grille(fichier: Path, g: Grille) -> np.ndarray:
    """Profondeur positive (m sous le zéro des cartes) sur la grille, NaN sans sondage."""
    with rasterio.open(fichier) as src:
        z = src.read(1).astype("float32")
        z[(z > 1e30) | (z < -1e4)] = np.nan
        sortie = np.full(g.forme, np.nan, "float32")
        reproject(z, sortie, src_transform=src.transform, src_crs=src.crs, src_nodata=np.nan,
                  dst_transform=g.transform, dst_crs=g.crs, dst_nodata=np.nan,
                  resampling=Resampling.average)
    return -sortie
