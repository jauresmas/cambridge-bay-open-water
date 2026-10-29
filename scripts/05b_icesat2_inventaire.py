"""05b. Inventaire des passages ICESat-2 ATL24 (bathymétrie lidar) sur la baie.

Seules les métadonnées sont interrogées (catalogue CMR de la NASA, sans
compte) : le téléchargement des données demande un compte Earthdata et n'est
pas fait ici. L'inventaire chiffre la piste d'une calibration de la
bathymétrie sans sondage, par le lidar.

Sortie : resultats/icesat2_atl24_granules.csv
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd
import requests
from pyproj import Transformer

from cbow import config

CMR = "https://cmr.earthdata.nasa.gov/search/granules.json"


def main():
    vers = Transformer.from_crs(config.CRS, "EPSG:4326", always_xy=True)
    x0, y0, x1, y1 = config.EMPRISE_BAIE
    o, s = vers.transform(x0, y0)
    e, n = vers.transform(x1, y1)
    r = requests.get(CMR, params={"short_name": "ATL24", "version": "002",
                                  "bounding_box": f"{o:.4f},{s:.4f},{e:.4f},{n:.4f}",
                                  "page_size": 2000}, timeout=120)
    r.raise_for_status()
    lignes = [dict(granule=g["title"], debut=g["time_start"][:19]) for g in r.json()["feed"]["entry"]]
    t = pd.DataFrame(lignes).drop_duplicates("granule").sort_values("debut")
    t["mois"] = t.debut.str.slice(5, 7).astype(int)
    t["eau_libre_probable"] = t.mois.isin([8, 9])
    t.to_csv(config.RESULTATS / "icesat2_atl24_granules.csv", index=False)
    print(f"{len(t)} granules ATL24 v2, dont {int(t.eau_libre_probable.sum())} en août ou septembre")


if __name__ == "__main__":
    main()
