"""Lacs, toponymes et masques de la zone d'étude."""
from __future__ import annotations

import os

os.environ.pop("PROJ_LIB", None)

import json
from pathlib import Path

import geopandas as gpd
import numpy as np
import requests
from rasterio import features
from shapely.geometry import LineString, Point, Polygon
from shapely.ops import linemerge, polygonize, unary_union

from . import config
from .grille import Grille

OVERPASS = "https://overpass-api.de/api/interpreter"
TOPONYMES = "https://geogratis.gc.ca/services/geoname/fr/geonames.json"
EN_TETES = {"User-Agent": "cambridge-bay-open-water/0.1"}


def _bbox_overpass():
    o, s, e, n = config.EMPRISE_LONLAT
    return f"{s},{o},{n},{e}"


def telecharger_eau_osm(cache: Path) -> dict:
    if cache.exists():
        return json.loads(cache.read_text(encoding="utf-8"))
    b = _bbox_overpass()
    q = (f'[out:json][timeout:180];(way["natural"="water"]({b});'
         f'relation["natural"="water"]({b}););out geom;')
    r = requests.post(OVERPASS, data={"data": q}, headers=EN_TETES, timeout=300)
    r.raise_for_status()
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_bytes(r.content)
    return r.json()


def _ligne(geom):
    return [(p["lon"], p["lat"]) for p in geom]


def polygones_osm(js: dict) -> gpd.GeoDataFrame:
    """Chemins fermés et multipolygones OSM en polygones (WGS 84)."""
    lignes = []
    for e in js["elements"]:
        tags = e.get("tags", {})
        if tags.get("water") in ("wastewater", "reservoir", "river", "canal"):
            continue
        if e["type"] == "way" and len(e.get("geometry", [])) >= 4:
            coords = _ligne(e["geometry"])
            if coords[0] == coords[-1]:
                lignes.append(dict(osm_id=f"w{e['id']}", nom_osm=tags.get("name"),
                                   geometry=Polygon(coords)))
        elif e["type"] == "relation":
            ext, inte = [], []
            for m in e.get("members", []):
                if m.get("type") != "way" or "geometry" not in m:
                    continue
                (inte if m.get("role") == "inner" else ext).append(LineString(_ligne(m["geometry"])))
            if not ext:
                continue
            polys_ext = list(polygonize(linemerge(ext)))
            polys_int = list(polygonize(linemerge(inte))) if inte else []
            if not polys_ext:
                continue
            geom = unary_union(polys_ext)
            if polys_int:
                geom = geom.difference(unary_union(polys_int))
            lignes.append(dict(osm_id=f"r{e['id']}", nom_osm=tags.get("name"), geometry=geom))
    gdf = gpd.GeoDataFrame(lignes, crs="EPSG:4326")
    gdf["geometry"] = gdf.geometry.buffer(0)
    return gdf[~gdf.geometry.is_empty]


def telecharger_toponymes(cache: Path) -> list[dict]:
    if cache.exists():
        return json.loads(cache.read_text(encoding="utf-8"))
    o, s, e, n = config.EMPRISE_LONLAT
    r = requests.get(TOPONYMES, params={"bbox": f"{o},{s},{e},{n}", "num": 1000},
                     headers=EN_TETES, timeout=120)
    r.raise_for_status()
    items = r.json()["items"]
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(items, ensure_ascii=False), encoding="utf-8")
    return items


def nommer_lacs(lacs: gpd.GeoDataFrame, toponymes: list[dict]) -> gpd.GeoDataFrame:
    """Rattache les toponymes officiels (BDTC) de lacs aux polygones.

    Un même lac porte souvent un nom inuinnaqtun et un nom anglais au même
    point : les deux sont conservés (« Iqaluktuuttiaq / Greiner Lake »).
    """
    pts = [t for t in toponymes if (t.get("concise") or {}).get("code") == "LAKE"]
    if not pts:
        lacs["nom"] = lacs["nom_osm"]
        return lacs
    # Les noms donnés au même point désignent la même entité (nom inuinnaqtun,
    # nom anglais, ancienne graphie) : on les regroupe par coordonnées.
    entites: dict[tuple, list[str]] = {}
    for t in pts:
        entites.setdefault((round(t["latitude"], 4), round(t["longitude"], 4)), []).append(t["name"])
    g = gpd.GeoDataFrame(
        dict(noms=list(entites.values())),
        geometry=[Point(lon, lat) for lat, lon in entites], crs="EPSG:4326",
    ).to_crs(lacs.crs)
    noms = {}
    for i, lac in lacs.iterrows():
        dedans = g[g.within(lac.geometry)]
        if len(dedans):
            # entité la plus proche du centre du lac ; nom inuinnaqtun d'abord,
            # nom anglais ensuite, sans l'ancienne graphie « Ekaloktotiak »
            proche = dedans.distance(lac.geometry.representative_point()).idxmin()
            vus = list(dict.fromkeys(dedans.loc[proche, "noms"]))
            anglais = [v for v in vus if v.endswith(" Lake")]
            autres = [v for v in vus if v not in anglais and v != "Ekaloktotiak"]
            noms[i] = " / ".join(autres + anglais)
    lacs["nom"] = [noms.get(i) or n for i, n in zip(lacs.index, lacs["nom_osm"])]
    return lacs


def lacs_projetes(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    lacs = gdf.to_crs(config.CRS)
    x0, y0, x1, y1 = config.EMPRISE
    cadre = Polygon([(x0, y0), (x1, y0), (x1, y1), (x0, y1)])
    lacs = lacs[lacs.within(cadre)].copy()   # lacs entiers seulement
    lacs["surface_km2"] = lacs.area / 1e6
    lacs = lacs.sort_values("surface_km2", ascending=False).reset_index(drop=True)
    lacs["lac_id"] = np.arange(1, len(lacs) + 1)
    return lacs


def raster_ids(lacs: gpd.GeoDataFrame, g: Grille, erosion: float) -> np.ndarray:
    """Identifiant de lac sur la grille, contour érodé de `erosion` mètres."""
    formes = []
    for lid, geom in zip(lacs["lac_id"], lacs.geometry):
        geom = geom.buffer(-erosion) if erosion > 0 else geom
        if not geom.is_empty:
            formes.append((geom, int(lid)))
    if not formes:
        return np.zeros(g.forme, "int32")
    return features.rasterize(formes, out_shape=g.forme, transform=g.transform,
                              fill=0, dtype="int32")


def masque_mer(eau_ete: np.ndarray, lacs_brut: np.ndarray, g: Grille) -> np.ndarray:
    """Mer : eau libre d'été hors lacs.

    On garde les composantes de plus de 20 km2, puis les bras plus petits
    (plus de 0,5 km2) séparés de la mer par un goulet plus étroit qu'un
    pixel, comme le bras du hameau.
    """
    from scipy import ndimage
    cand = eau_ete & (lacs_brut == 0)
    lab, n = ndimage.label(cand)
    if n == 0:
        return cand
    tailles = ndimage.sum(np.ones_like(lab), lab, index=np.arange(1, n + 1))
    km2 = tailles * g.res * g.res / 1e6
    mer = np.isin(lab, np.flatnonzero(km2 > 20) + 1)
    voisinage = ndimage.binary_dilation(mer, iterations=max(1, int(160 / g.res)))
    touche = np.unique(lab[voisinage & cand & ~mer])
    touche = [t for t in touche if t > 0 and km2[t - 1] > 0.5]
    return mer | np.isin(lab, touche)
