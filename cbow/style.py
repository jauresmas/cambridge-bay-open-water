"""Style commun des figures : couleurs fixes par capteur, virgule décimale."""
from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter

# Une couleur par capteur, toujours la même d'une figure à l'autre
# (trois premières teintes d'une palette vérifiée pour les daltonismes).
CAPTEURS = {"Sentinel-1": "#2a78d6", "Sentinel-2": "#eb6834", "Landsat TIRS": "#1baf7a",
            "fusion": "#0b0b0b"}
NOMS_CAPTEURS = {"Sentinel-1": "Radar Sentinel-1", "Sentinel-2": "Optique Sentinel-2",
                 "Landsat TIRS": "Thermique Landsat", "fusion": "Fusion"}
ENCRE, ENCRE_2, MUET = "#0b0b0b", "#52514e", "#898781"
GRILLE, AXE, FOND = "#e1e0d9", "#c3c2b7", "#fcfcfb"
BLEU = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"]
DIVERGENT = ("#256abf", "#f0efec", "#c63b3b")


def appliquer():
    plt.rcParams.update({
        "font.family": ["Segoe UI", "DejaVu Sans"],
        "font.size": 9.5, "axes.titlesize": 10.5, "axes.titleweight": "semibold",
        "axes.titlelocation": "left", "axes.labelcolor": ENCRE_2, "axes.edgecolor": AXE,
        "axes.linewidth": 0.8, "axes.spines.top": False, "axes.spines.right": False,
        "axes.grid": True, "grid.color": GRILLE, "grid.linewidth": 0.6,
        "xtick.color": MUET, "ytick.color": MUET, "xtick.labelcolor": ENCRE_2,
        "ytick.labelcolor": ENCRE_2, "legend.frameon": False, "figure.facecolor": "white",
        "axes.facecolor": "white", "savefig.dpi": 200, "savefig.bbox": "tight",
        "lines.linewidth": 1.6, "axes.formatter.use_locale": False,
    })


def virgule(decimales: int = 1):
    """Formateur d'axe à la française (virgule décimale)."""
    def f(x, _pos=None):
        s = f"{x:.{decimales}f}" if decimales else f"{x:.0f}"
        return s.replace(".", ",")
    return FuncFormatter(f)


def nombre(x, decimales=1) -> str:
    return f"{x:.{decimales}f}".replace(".", ",")


def enregistrer(fig, chemin):
    chemin.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(chemin)
    plt.close(fig)
