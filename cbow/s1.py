"""Sentinel-1 EW GRDM (HH) : calibration en sigma0 et projection sur la grille.

Chaîne par scène :
1. fenêtre de l'image (géométrie radar) qui couvre la zone, estimée à partir
   des points d'appui (GCP) fournis avec le produit ;
2. lecture du compte numérique DN dans cette fenêtre, à pleine résolution ou
   sur un aperçu ;
3. sigma0 = (DN^2 - bruit) / A^2, avec A la table sigmaNought de
   l'annotation de calibration et le bruit thermique en distance et en azimut
   (annotations IPF 2.9 et suivantes) ;
4. reprojection sur la grille UTM par les GCP voisins de la fenêtre.

La zone est presque plate (moins de 200 m de relief) : la géométrie GRD sans
correction de terrain suffit à l'échelle de 40 à 80 m.
"""
from __future__ import annotations

import os

os.environ.pop("PROJ_LIB", None)

import xml.etree.ElementTree as ET
from dataclasses import dataclass

import numpy as np
import rasterio
from pyproj import Transformer
from rasterio.control import GroundControlPoint
from rasterio.enums import Resampling
from rasterio.warp import reproject
from rasterio.windows import Window

from . import stac
from .grille import Grille

COLLECTION = "sentinel-1-grd"


# ---------------------------------------------------------------------------
# Lecture des annotations
# ---------------------------------------------------------------------------
def _nombres(texte: str) -> np.ndarray:
    return np.array(texte.split(), dtype="float64")


@dataclass
class TableLignes:
    """Table définie vecteur par vecteur : une ligne, des pixels, des valeurs."""
    lignes: np.ndarray            # (n,)
    pixels: list[np.ndarray]      # n tableaux
    valeurs: list[np.ndarray]     # n tableaux

    def evaluer(self, rangs: np.ndarray, colonnes: np.ndarray) -> np.ndarray:
        """Interpolation bilinéaire sur une grille séparable (rangs x colonnes)."""
        par_vecteur = np.stack([np.interp(colonnes, p, v)
                                for p, v in zip(self.pixels, self.valeurs)])
        i = np.clip(np.searchsorted(self.lignes, rangs) - 1, 0, len(self.lignes) - 2)
        l0, l1 = self.lignes[i], self.lignes[i + 1]
        w = np.clip((rangs - l0) / np.maximum(l1 - l0, 1), 0, 1)[:, None]
        return par_vecteur[i] * (1 - w) + par_vecteur[i + 1] * w


def lire_calibration(xml: str) -> TableLignes:
    racine = ET.fromstring(xml)
    lignes, pixels, valeurs = [], [], []
    for v in racine.iter("calibrationVector"):
        lignes.append(float(v.findtext("line")))
        pixels.append(_nombres(v.findtext("pixel")))
        valeurs.append(_nombres(v.findtext("sigmaNought")))
    return TableLignes(np.array(lignes), pixels, valeurs)


@dataclass
class BlocAzimut:
    premiere_ligne: int
    derniere_ligne: int
    premier_pixel: int
    dernier_pixel: int
    lignes: np.ndarray
    valeurs: np.ndarray


def lire_bruit(xml: str) -> tuple[TableLignes | None, list[BlocAzimut]]:
    racine = ET.fromstring(xml)
    lignes, pixels, valeurs = [], [], []
    # IPF >= 2.9 : noiseRangeVector ; versions antérieures : noiseVector
    for v in list(racine.iter("noiseRangeVector")) + list(racine.iter("noiseVector")):
        lut = v.findtext("noiseRangeLut") or v.findtext("noiseLut")
        lignes.append(float(v.findtext("line")))
        pixels.append(_nombres(v.findtext("pixel")))
        valeurs.append(_nombres(lut))
    distance = TableLignes(np.array(lignes), pixels, valeurs) if lignes else None
    blocs = []
    for v in racine.iter("noiseAzimuthVector"):
        lig = v.find("line")
        if lig is None or not (lig.text or "").strip():
            continue
        blocs.append(BlocAzimut(
            int(v.findtext("firstAzimuthLine")), int(v.findtext("lastAzimuthLine")),
            int(v.findtext("firstRangeSample")), int(v.findtext("lastRangeSample")),
            _nombres(lig.text), _nombres(v.findtext("noiseAzimuthLut"))))
    return distance, blocs


def bruit_azimut(blocs: list[BlocAzimut], rangs: np.ndarray, colonnes: np.ndarray) -> np.ndarray:
    sortie = np.ones((len(rangs), len(colonnes)))
    for b in blocs:
        r = (rangs >= b.premiere_ligne) & (rangs <= b.derniere_ligne)
        c = (colonnes >= b.premier_pixel) & (colonnes <= b.dernier_pixel)
        if not r.any() or not c.any():
            continue
        if len(b.lignes) == 1:
            val = np.full(r.sum(), b.valeurs[0])
        else:
            val = np.interp(rangs[r], b.lignes, b.valeurs)
        sortie[np.ix_(r, c)] = val[:, None]
    return sortie


def lire_incidence(xml: str) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    racine = ET.fromstring(xml)
    pts = [(float(p.findtext("line")), float(p.findtext("pixel")),
            float(p.findtext("incidenceAngle")))
           for p in racine.iter("geolocationGridPoint")]
    a = np.array(pts)
    return a[:, 0], a[:, 1], a[:, 2]


# ---------------------------------------------------------------------------
# Géométrie
# ---------------------------------------------------------------------------
def _ajuster_polynome(x, y, z):
    A = np.column_stack([np.ones_like(x), x, y, x * x, x * y, y * y])
    coef, *_ = np.linalg.lstsq(A, z, rcond=None)
    return lambda u, v: np.column_stack(
        [np.ones_like(u), u, v, u * u, u * v, v * v]) @ coef


def fenetre_zone(gcps, g: Grille, forme_image, marge=24) -> Window | None:
    """Fenêtre (géométrie radar) qui couvre la grille, ou None hors champ."""
    vers_utm = Transformer.from_crs("EPSG:4326", g.crs, always_xy=True)
    lon = np.array([p.x for p in gcps]); lat = np.array([p.y for p in gcps])
    x, y = vers_utm.transform(lon, lat)
    rang = np.array([p.row for p in gcps]); col = np.array([p.col for p in gcps])
    f_r, f_c = _ajuster_polynome(x, y, rang), _ajuster_polynome(x, y, col)
    bx = np.linspace(g.xmin, g.xmax, 9); by = np.linspace(g.ymin, g.ymax, 9)
    BX, BY = np.meshgrid(bx, by)
    rr, cc = f_r(BX.ravel(), BY.ravel()), f_c(BX.ravel(), BY.ravel())
    hauteur, largeur = forme_image
    r0, r1 = max(int(rr.min()) - marge, 0), min(int(rr.max()) + marge, hauteur)
    c0, c1 = max(int(cc.min()) - marge, 0), min(int(cc.max()) + marge, largeur)
    if r1 - r0 < 50 or c1 - c0 < 50:
        return None
    return Window(c0, r0, c1 - c0, r1 - r0)


def _gcps_locaux(gcps, fen: Window, facteur: int):
    """GCP au voisinage de la fenêtre, recalés sur le tableau lu."""
    marge_r = fen.height * 0.6 + 600
    marge_c = fen.width * 0.6 + 600
    rc = fen.row_off + fen.height / 2
    cc = fen.col_off + fen.width / 2
    locaux = [GroundControlPoint(row=(p.row - fen.row_off) / facteur,
                                 col=(p.col - fen.col_off) / facteur,
                                 x=p.x, y=p.y, z=p.z)
              for p in gcps
              if abs(p.row - rc) <= marge_r and abs(p.col - cc) <= marge_c]
    return locaux if len(locaux) >= 9 else [
        GroundControlPoint(row=(p.row - fen.row_off) / facteur,
                           col=(p.col - fen.col_off) / facteur, x=p.x, y=p.y, z=p.z)
        for p in gcps]


# ---------------------------------------------------------------------------
# Scène complète
# ---------------------------------------------------------------------------
def sigma0_sur_grille(scene: dict, g: Grille, facteur: int = 1,
                      pol: str = "hh") -> dict | None:
    """sigma0 (linéaire) d'une scène sur la grille, ou None hors champ.

    `facteur` = 1 lit la pleine résolution (40 m en EW GRDM), 2 l'aperçu
    suivant (80 m), ce qui divise le volume téléchargé par quatre.
    """
    a = scene["assets"]
    with rasterio.Env(**stac.ENV_GDAL):
        with rasterio.open(stac.signer(a[pol]["href"], COLLECTION)) as src:
            gcps, _ = src.gcps
            fen = fenetre_zone(gcps, g, (src.height, src.width))
            if fen is None:
                return None
            h = max(int(fen.height // facteur), 1)
            w = max(int(fen.width // facteur), 1)
            dn = src.read(1, window=fen, out_shape=(h, w),
                          resampling=Resampling.average).astype("float64")

    rangs = fen.row_off + (np.arange(h) + 0.5) * facteur - 0.5
    colonnes = fen.col_off + (np.arange(w) + 0.5) * facteur - 0.5
    cal = lire_calibration(stac.lire_texte(a[f"schema-calibration-{pol}"]["href"], COLLECTION))
    A = cal.evaluer(rangs, colonnes)
    distance, blocs = lire_bruit(stac.lire_texte(a[f"schema-noise-{pol}"]["href"], COLLECTION))
    bruit = 0.0
    if distance is not None:
        bruit = distance.evaluer(rangs, colonnes) * bruit_azimut(blocs, rangs, colonnes)
    puissance = dn * dn
    sigma0 = (puissance - bruit) / (A * A)
    sigma0[dn <= 0] = np.nan
    # le bruit retranché peut rendre le signal négatif sur les cibles très sombres
    sigma0 = np.where(np.isfinite(sigma0), np.maximum(sigma0, 1e-4), np.nan)

    # Depuis fin 2021, le lien « schema-product » du catalogue pointe vers
    # l'annotation RFI : on reconstruit le chemin de l'annotation produit.
    annotation = a[f"schema-calibration-{pol}"]["href"].replace("calibration/calibration-", "")
    lig, pix, inc = lire_incidence(stac.lire_texte(annotation, COLLECTION))
    centre_r = fen.row_off + fen.height / 2
    centre_c = fen.col_off + fen.width / 2
    proches = np.argsort((lig - centre_r) ** 2 + ((pix - centre_c) * 1.0) ** 2)[:4]
    incidence = float(np.mean(inc[proches]))

    sortie = np.full(g.forme, np.nan, dtype="float32")
    reproject(source=sigma0.astype("float32"), destination=sortie,
              gcps=_gcps_locaux(gcps, fen, facteur), src_crs="EPSG:4326",
              src_nodata=np.nan, dst_transform=g.transform, dst_crs=g.crs,
              dst_nodata=np.nan, resampling=Resampling.average)
    p = scene["properties"]
    return dict(sigma0=sortie, incidence=incidence, date=p["datetime"],
                plateforme=p.get("platform", ""), orbite=p.get("sat:relative_orbit"),
                passage=p.get("sat:orbit_state", ""), id=scene["id"])


def en_db(lineaire: np.ndarray) -> np.ndarray:
    with np.errstate(divide="ignore", invalid="ignore"):
        return 10 * np.log10(lineaire)
