"""Tests des méthodes sur des cas construits, sans réseau."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
import pandas as pd
import pytest

from cbow import bathy, landsat, meteo, phenologie, s1, s2


# --- Phénologie -------------------------------------------------------------
def serie(dates, glace, eau):
    return pd.DataFrame(dict(date=pd.to_datetime(dates), glace=glace, eau=eau))


def test_debacle_encadree_par_les_observations():
    obs = serie(["2020-06-01", "2020-06-20", "2020-07-02", "2020-07-10", "2020-08-01"],
                [1.0, 0.8, 0.3, 0.0, 0.0], [0.0, 0.1, 0.6, 1.0, 1.0])
    t = phenologie.debacle_s2(obs, 2020)
    assert t.avant == pd.Timestamp("2020-07-02")
    assert t.apres == pd.Timestamp("2020-07-10")
    assert t.date == pd.Timestamp("2020-07-06")
    assert t.demi_largeur == 4


def test_debacle_tolere_une_observation_aberrante():
    # un nuage mal masqué pris pour de la glace après l'ouverture
    obs = serie(["2020-06-20", "2020-07-05", "2020-07-15", "2020-07-25"],
                [0.9, 0.0, 0.5, 0.0], [0.1, 1.0, 0.5, 1.0])
    assert phenologie.debacle_s2(obs, 2020).apres == pd.Timestamp("2020-07-05")


def test_sans_observation_de_l_etat_ancien():
    obs = serie(["2020-07-10", "2020-08-01"], [0.0, 0.0], [1.0, 1.0])
    t = phenologie.debacle_s2(obs, 2020)
    assert t.avant is None and t.date is None and np.isnan(t.demi_largeur)


def test_prise_thermique_exige_une_surface_sous_zero():
    obs = pd.DataFrame(dict(date=pd.to_datetime(["2020-09-20", "2020-10-01", "2020-10-12"]),
                            t_med=[3.0, 0.2, -4.0], t_p90=[4.0, 0.8, -2.5], t_p10=[2.0, -0.5, -6.0]))
    t = phenologie.prise_thermique(obs, 2020)
    assert t.avant == pd.Timestamp("2020-09-20") and t.apres == pd.Timestamp("2020-10-12")


def test_normalisation_incidence_retrouve_la_pente():
    rng = np.random.default_rng(1)
    d = pd.date_range("2019-01-05", "2019-04-25", periods=60)
    inc = rng.uniform(20, 45, 60)
    obs = pd.DataFrame(dict(date=d, incidence=inc, db_med=-12 - 0.25 * (inc - 35)
                            + rng.normal(0, 0.1, 60)))
    norm, pente = phenologie.normaliser_incidence(obs)
    assert pente == pytest.approx(-0.25, abs=0.02)
    assert norm.std() < 0.2


def test_fonte_premiere_detection_confirmee():
    d = pd.date_range("2021-02-01", "2021-07-30", freq="4D")
    db = np.full(len(d), -12.0)
    i = np.searchsorted(d, pd.Timestamp("2021-06-10"))
    db[i] = -17         # première neige humide
    db[i + 1] = -12.5   # passage du matin, neige regelée
    db[i + 2:] = -18
    obs = pd.DataFrame(dict(date=d, db_norm=db))
    t = phenologie.fonte_s1(obs, 2021)
    assert t.apres == d[i]


# --- Météo ------------------------------------------------------------------
def test_stefan_et_degres_jours():
    jours = pd.date_range("2019-09-01", "2020-04-30", freq="D")
    tair = pd.Series(-20.0, index=jours)
    dj = meteo.degres_jours(tair)
    assert dj["djg"].iloc[-1] == pytest.approx(20 * len(jours))
    assert meteo.stefan(5000, 0.024) == pytest.approx(0.024 * np.sqrt(5000))


def test_annee_de_glace_commence_en_septembre():
    d = pd.to_datetime(["2019-08-31", "2019-09-01", "2020-03-01"])
    assert list(meteo.annee_glace(d)) == [2019, 2020, 2020]


# --- Sentinel-1 -------------------------------------------------------------
def test_table_calibration_bilineaire():
    t = s1.TableLignes(np.array([0.0, 10.0]),
                       [np.array([0.0, 10.0]), np.array([0.0, 10.0])],
                       [np.array([1.0, 3.0]), np.array([5.0, 7.0])])
    v = t.evaluer(np.array([0.0, 5.0, 10.0]), np.array([0.0, 5.0, 10.0]))
    assert v[1, 1] == pytest.approx(4.0)
    assert v[0, 2] == pytest.approx(3.0) and v[2, 0] == pytest.approx(5.0)


def test_bruit_azimut_par_bloc():
    b = s1.BlocAzimut(0, 9, 0, 4, np.array([0.0, 9.0]), np.array([1.0, 2.0]))
    v = s1.bruit_azimut([b], np.arange(10.0), np.arange(8.0))
    assert v[9, 0] == pytest.approx(2.0)
    assert v[0, 7] == 1.0     # hors du bloc : facteur neutre


# --- Sentinel-2 et Landsat ---------------------------------------------------
def test_classes_optiques():
    vert = np.array([0.03, 0.6, 0.6, 0.05, 0.11, 0.30])
    swir = np.array([0.01, 0.05, 0.4, 0.01, 0.01, 0.02])
    scl = np.array([6, 11, 8, 6, 6, 6])
    c = s2.classer(vert, swir, scl)
    # eau turbide classée « eau » par Sen2Cor : eau ; même classe mais très claire : glace
    assert list(c) == [s2.EAU, s2.GLACE, s2.NUAGE, s2.EAU, s2.EAU, s2.GLACE]


def test_transition_tolere_une_part_d_aberrations():
    # deux voiles pris pour de la glace parmi quinze observations d'eau libre
    d = pd.date_range("2024-07-01", periods=18, freq="3D")
    glace = np.r_[[1.0, 1.0], np.zeros(16)]
    glace[[6, 11]] = 0.9
    eau = 1 - glace
    t = phenologie.debacle_s2(serie(d, glace, eau), 2024)
    assert t.apres == d[2]


def test_fonte_ignoree_par_grand_froid():
    d = pd.date_range("2022-02-01", "2022-07-30", freq="5D")
    db = np.full(len(d), -12.0)
    i = np.searchsorted(d, pd.Timestamp("2022-04-21"))
    db[i:i + 2] = -18          # baisse radar par -19 °C : artefact
    j = np.searchsorted(d, pd.Timestamp("2022-06-10"))
    db[j:] = -18
    tair = pd.Series(np.where(pd.date_range("2022-01-01", "2022-08-31").month < 6, -19.0, 2.0),
                     index=pd.date_range("2022-01-01", "2022-08-31"))
    t = phenologie.fonte_s1(pd.DataFrame(dict(date=d, db_norm=db)), 2022, tair=tair)
    assert t.apres == d[j]


def test_masque_qa_landsat():
    clair = 1 << 6
    nuage = (1 << 3) | (1 << 1)
    assert list(landsat.masque_qa(np.array([clair, nuage, 0]))) == [True, False, False]


# --- Bathymétrie ------------------------------------------------------------
def test_stumpf_retrouve_une_profondeur_synthetique():
    rng = np.random.default_rng(0)
    z = rng.uniform(0.5, 12, 4000)
    # atténuation plus forte dans le bleu que dans le vert : le rapport croît avec z
    bleu = 0.01 + 0.05 * np.exp(-0.25 * z)
    vert = 0.01 + 0.06 * np.exp(-0.12 * z)
    rouge = 0.002 + 0.05 * np.exp(-0.6 * z)
    x = rng.uniform(0, 20000, 4000)
    y = rng.uniform(0, 20000, 4000)
    df = pd.DataFrame(bathy.variables(bleu, vert, rouge))
    df["z"] = z
    plis = bathy.blocs(x, y, 2000, 5)
    pred = bathy.validation_croisee(df, bathy.MODELES["Lyzenga 3 bandes"], plis)
    s = bathy.scores(z, pred)
    assert s["r2"] > 0.9


def test_blocs_regroupent_les_voisins():
    x = np.array([10.0, 20.0, 5000.0])
    y = np.array([10.0, 30.0, 5000.0])
    p = bathy.blocs(x, y, 1000, 5)
    assert p[0] == p[1]
