"""Chaîne complète, dans l'ordre. Chaque étape reprend là où elle s'est arrêtée.

python scripts/run_all.py            tout
python scripts/run_all.py 07 08 09   seulement ces étapes

Durée d'une première exécution complète : quelques heures, surtout pour
télécharger les séries (environ 3 Go dans data/). L'étape 11 (projet QGIS)
se lance avec le Python de QGIS 3.34, s'il est installé.
"""
import subprocess
import sys
from pathlib import Path

ICI = Path(__file__).resolve().parent
ETAPES = ["00_zone", "01_meteo", "02_s1_series", "03_s2_series", "04_landsat_thermique",
          "05_bathymetrie", "05b_icesat2_inventaire", "06_glace_ancree", "07_phenologie", "08_figures",
          "10_couches_qgis", "11_projet_qgis", "09_article"]
QGIS_PYTHON = Path(r"C:\Program Files\QGIS 3.34.12\bin\python-qgis-ltr.bat")

if __name__ == "__main__":
    choix = sys.argv[1:]
    for e in ETAPES:
        if choix and not any(e.startswith(c) for c in choix):
            continue
        print(f"\n=== {e}", flush=True)
        if e == "11_projet_qgis":
            if not QGIS_PYTHON.exists():
                print("QGIS 3.34 introuvable : projet QGIS non reconstruit")
                continue
            r = subprocess.run([str(QGIS_PYTHON), str(ICI / f"{e}.py")], cwd=ICI.parent)
        else:
            r = subprocess.run([sys.executable, str(ICI / f"{e}.py")], cwd=ICI.parent)
        if r.returncode:
            sys.exit(f"échec de l'étape {e}")
