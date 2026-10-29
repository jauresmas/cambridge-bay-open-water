"""Recherche STAC et signature des liens du Planetary Computer.

Le catalogue est lu sans compte : l'API renvoie un jeton SAS anonyme par
collection, à ajouter aux liens des fichiers. Aucun paquet spécifique
(pystac-client, planetary-computer) n'est nécessaire.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import requests

from . import config

_JETONS: dict[str, tuple[str, float]] = {}
SESSION = requests.Session()
SESSION.headers["User-Agent"] = "cambridge-bay-open-water/0.1"  # ASCII seulement


def _requete(methode: str, url: str, **kw) -> requests.Response:
    for essai in range(6):
        try:
            r = SESSION.request(methode, url, timeout=120, **kw)
            if r.status_code in (429, 500, 502, 503, 504):
                raise requests.HTTPError(f"{r.status_code}")
            r.raise_for_status()
            return r
        except (requests.RequestException, ValueError):
            if essai == 5:
                raise
            time.sleep(2 * (essai + 1))
    raise RuntimeError("inaccessible")


def chercher(collection: str, debut: str, fin: str, bbox=None, requete=None,
             cache: Path | None = None) -> list[dict]:
    """Toutes les scènes d'une collection sur l'emprise et la période."""
    if cache is not None and cache.exists():
        return json.loads(cache.read_text(encoding="utf-8"))
    corps = {
        "collections": [collection],
        "bbox": list(bbox or config.EMPRISE_LONLAT),
        "datetime": f"{debut}/{fin}",
        "limit": 1000,
    }
    if requete:
        corps["query"] = requete
    scenes = []
    while True:
        js = _requete("POST", f"{config.STAC_PC}/search", json=corps).json()
        scenes += js["features"]
        suivant = [l for l in js.get("links", []) if l.get("rel") == "next"]
        if not suivant:
            break
        corps = suivant[0]["body"]
    if cache is not None:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(scenes), encoding="utf-8")
    return scenes


def jeton(collection: str) -> str:
    """Jeton SAS anonyme, renouvelé un quart d'heure avant expiration."""
    tok, expire = _JETONS.get(collection, ("", 0.0))
    if time.time() < expire - 900:
        return tok
    js = _requete("GET", f"{config.SAS_PC}/{collection}").json()
    tok = js["token"]
    # durée de validité d'environ une heure au minimum
    _JETONS[collection] = (tok, time.time() + 3600)
    return tok


def signer(href: str, collection: str) -> str:
    return f"{href}?{jeton(collection)}"


def lire_texte(href: str, collection: str) -> str:
    return _requete("GET", signer(href, collection)).text


ENV_GDAL = dict(
    GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR",
    CPL_VSIL_CURL_ALLOWED_EXTENSIONS=".tif,.tiff,.TIF",
    GDAL_HTTP_MAX_RETRY="5",
    GDAL_HTTP_RETRY_DELAY="3",
    GDAL_HTTP_MULTIRANGE="YES",
    GDAL_HTTP_MERGE_CONSECUTIVE_RANGES="YES",
    VSI_CACHE="TRUE",
)
