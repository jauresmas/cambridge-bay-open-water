"""Paramètres communs : zone d'étude, grilles, années, chemins, seuils.

Tous les seuils de classification sont rassemblés ici pour être cités dans la
note de méthode et modifiés en un seul endroit.
"""
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
DATA = RACINE / "data"
RESULTATS = RACINE / "resultats"
FIGURES = RACINE / "figures"

# Zone d'étude : Cambridge Bay (Iqaluktuuttiaq), île Victoria, Nunavut.
# UTM 13 N, emprise de 60 km sur 55 km centrée sur le hameau, la baie et
# Greiner Lake.
CRS = "EPSG:32613"
EMPRISE = (470000.0, 7640000.0, 530000.0, 7695000.0)  # xmin, ymin, xmax, ymax
EMPRISE_LONLAT = (-105.62, 68.90, -104.40, 69.40)       # pour les recherches STAC

# Sous-zone de la bathymétrie : la baie intérieure et son entrée.
EMPRISE_BAIE = (478000.0, 7645000.0, 506000.0, 7670000.0)

HAMEAU = (-105.0528, 69.1139)

# Résolutions de travail (m)
RES_S1_SERIE = 80.0    # séries temporelles radar (aperçu x2 du GRDM à 40 m)
RES_S1_CARTE = 40.0    # cartes de glace ancrée (résolution native du GRDM)
RES_S2_SERIE = 80.0    # séries temporelles optiques (aperçus des COG)
RES_S2_BATHY = 10.0    # bathymétrie
RES_LANDSAT = 90.0     # thermique Landsat (bande ST à 100 m rééchantillonnée)

ANNEES = list(range(2017, 2026))

# Catalogue
STAC_PC = "https://planetarycomputer.microsoft.com/api/stac/v1"
SAS_PC = "https://planetarycomputer.microsoft.com/api/sas/v1/token"

# Météo : stations ECCC du hameau (identifiants climatologiques), par ordre de
# préférence ; la série quotidienne est reconstituée en comblant les trous de
# la première par les suivantes.
STATIONS_ECCC = ["2400601", "2400603", "2400602"]

# Lacs retenus pour les séries : surface minimale (km2) et érosion du contour
# (m) pour écarter les pixels mêlés à la rive.
LAC_SURFACE_MIN_KM2 = 1.0
LAC_EROSION_M = 120.0

# Sentinel-2 : réflectances de surface (L2A, échelle 1/10000, décalage de
# 1000 à partir de la version de traitement 04.00).
S2_ZENITH_MAX = 80.0          # angle zénithal solaire maximal (degrés)
S2_NUAGES_MAX = 80.0          # couverture nuageuse maximale de la tuile (%)
S2_SCL_NUAGES = (3, 8, 9, 10)  # ombre, nuages moyens et hauts, cirrus
S2_NDSI_GLACE = 0.42          # au-dessus : neige ou glace
S2_VERT_GLACE = 0.10          # réflectance verte minimale de la glace
S2_VERT_EAU = 0.08            # en dessous : eau libre
S2_VERT_EAU_SCL = 0.20        # classe « eau » de Sen2Cor retenue sous ce vert
S2_SWIR_NUAGE = 0.20          # SWIR plus fort : nuage (glace et eau sont sombres)

# Seuils de décision sur la fraction d'un lac
FRACTION_GLACE = 0.9
FRACTION_EAU = 0.9
FRACTION_VALIDE_MIN = 0.6     # part minimale du lac observée sans nuage

# Sentinel-1 : glace ancrée (posée sur le fond) ou flottante en fin d'hiver
S1_FIN_HIVER = ("04-01", "04-30")
S1_DEBUT_HIVER = ("11-15", "12-15")

# Fonte : baisse de la rétrodiffusion par rapport à la référence hivernale
S1_SEUIL_NEIGE_HUMIDE_DB = -3.0

# Stefan : épaisseur de glace h = alpha * sqrt(DJG), h en m, DJG en degrés-jours
STEFAN_ALPHA = 0.024   # coefficient de lac, ~0.017 à 0.027 m (°C j)^-0.5

# Bathymétrie
BATHY_PROF_MAX = 20.0         # profondeurs de calibration retenues (m)
BATHY_BLOC_M = 1500.0         # taille des blocs de la validation croisée
BATHY_PLIS = 5
