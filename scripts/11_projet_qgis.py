"""11. Projet QGIS, carte mise en page et modèles graphiques (PyQGIS, QGIS 3.34).

À lancer avec le Python de QGIS :
    "C:/Program Files/QGIS 3.34.12/bin/python-qgis-ltr.bat" scripts/11_projet_qgis.py

Produit
- qgis/cambridge_bay.qgz : couches stylées (lacs et dates médianes, eau libre
  par lac et par année pour le contrôleur temporel, régime de glace,
  bathymétrie), mise en page « Eau libre par lac » ;
- figures/07_eau_libre_lacs.png : export de cette mise en page ;
- qgis/modeles/rapport_stumpf.model3 et mediane_radar_lacs.model3 : deux
  étapes de la chaîne refaites dans le modeleur graphique ;
- resultats/controle_qgis.csv : écart entre les modèles QGIS et la chaîne
  Python sur les mêmes données.
"""
import os
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))

from qgis.core import (
    QgsApplication, QgsProject, QgsCoordinateReferenceSystem, QgsRasterLayer, QgsVectorLayer,
    QgsGraduatedSymbolRenderer, QgsRendererRange, QgsFillSymbol, QgsMarkerSymbol, QgsLineSymbol,
    QgsSingleSymbolRenderer, QgsPalettedRasterRenderer, QgsColorRampShader, QgsRasterShader,
    QgsSingleBandPseudoColorRenderer, QgsVectorLayerTemporalProperties, QgsPalLayerSettings,
    QgsTextFormat, QgsTextBufferSettings, QgsVectorLayerSimpleLabeling, QgsPrintLayout,
    QgsLayoutItemMap, QgsLayoutItemLabel, QgsLayoutItemLegend, QgsLayoutItemScaleBar,
    QgsLayoutItemPicture, QgsLayoutPoint, QgsLayoutSize, QgsUnitTypes, QgsRectangle, QgsLayerTree,
    QgsLayoutExporter, QgsLegendStyle, QgsScaleBarSettings, QgsProcessingModelAlgorithm, QgsProcessingModelParameter,
    QgsProcessingModelChildAlgorithm, QgsProcessingModelChildParameterSource, QgsProcessingModelOutput,
    QgsProcessingParameterRasterLayer, QgsProcessingParameterVectorLayer, QgsProcessingFeedback,
)
from qgis.PyQt.QtGui import QColor, QFont

from cbow import config

QGIS_PLUGINS = Path(r"C:\Program Files\QGIS 3.34.12\apps\qgis-ltr\python\plugins")
BLEU = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"]
POLICE = "Segoe UI"
Q = RACINE / "qgis"
RQ = config.RESULTATS / "qgis"
GPKG = RQ / "cambridge_bay.gpkg"


def couche_gpkg(nom, titre):
    lyr = QgsVectorLayer(f"{GPKG}|layername={nom}", titre, "ogr")
    assert lyr.isValid(), nom
    return lyr


def raster(chemin, titre):
    lyr = QgsRasterLayer(str(chemin), titre)
    assert lyr.isValid(), chemin
    return lyr


def texte(taille=9, gras=False, couleur="#0b0b0b"):
    f = QgsTextFormat()
    police = QFont(POLICE)
    police.setBold(gras)
    f.setFont(police)
    f.setSize(taille)
    f.setColor(QColor(couleur))
    return f


# ---------------------------------------------------------------------------
def styler_lacs(lyr):
    bornes = [(75, 85), (85, 90), (90, 95), (95, 102)]
    plages = []
    for (a, b), c in zip(bornes, [BLEU[1], BLEU[3], BLEU[4], BLEU[6]]):
        s = QgsFillSymbol.createSimple({"color": c, "outline_color": "#0d366b", "outline_width": "0.15"})
        plages.append(QgsRendererRange(a, b, s, f"{a} à {b} jours"))
    r = QgsGraduatedSymbolRenderer("eau_libre_j", plages)
    lyr.setRenderer(r)
    reg = QgsPalLayerSettings()
    reg.fieldName = "nom"
    f = texte(7.5, True)
    tampon = QgsTextBufferSettings()
    tampon.setEnabled(True)
    tampon.setSize(0.8)
    tampon.setColor(QColor("white"))
    f.setBuffer(tampon)
    reg.setFormat(f)
    lyr.setLabeling(QgsVectorLayerSimpleLabeling(reg))
    lyr.setLabelsEnabled(True)


def styler_temporel(lyr):
    lyr.setRenderer(QgsSingleSymbolRenderer(QgsFillSymbol.createSimple(
        {"color": "#3987e5", "outline_color": "#0d366b", "outline_width": "0.1"})))
    tp = lyr.temporalProperties()
    tp.setIsActive(True)
    tp.setMode(QgsVectorLayerTemporalProperties.ModeFeatureDateTimeStartAndEndFromFields)
    tp.setStartField("debacle")
    tp.setEndField("prise")


def paletted(lyr, classes):
    cls = [QgsPalettedRasterRenderer.Class(v, QColor(c), lab) for v, c, lab in classes]
    lyr.setRenderer(QgsPalettedRasterRenderer(lyr.dataProvider(), 1, cls))


def pseudo(lyr, vmin, vmax, couleurs, etiquette):
    sh = QgsColorRampShader(vmin, vmax)
    sh.setColorRampType(QgsColorRampShader.Interpolated)
    pas = (vmax - vmin) / (len(couleurs) - 1)
    sh.setColorRampItemList([QgsColorRampShader.ColorRampItem(vmin + i * pas, QColor(c),
                                                               f"{vmin + i * pas:.0f} {etiquette}")
                             for i, c in enumerate(couleurs)])
    rs = QgsRasterShader()
    rs.setRasterShaderFunction(sh)
    lyr.setRenderer(QgsSingleBandPseudoColorRenderer(lyr.dataProvider(), 1, rs))


def construire_projet():
    proj = QgsProject.instance()
    proj.clear()
    proj.setCrs(QgsCoordinateReferenceSystem("EPSG:32613"))
    proj.setTitle("Cambridge Bay, la fenêtre d'eau libre")
    md = proj.metadata()
    md.setAuthor("Jaurès DAA-HINGBANON")
    md.setAbstract("Glace des lacs et bathymétrie côtière autour de Cambridge Bay (Nunavut), 2017-2025, "
                   "à partir de Sentinel-1, Sentinel-2 et Landsat. Couches produites par la chaîne Python du dépôt.")
    proj.setMetadata(md)
    racine = proj.layerTreeRoot()

    fond = raster(RQ / "fond_sentinel2_ete_40m.tif", "Sentinel-2, 7 août 2024")
    lacs = couche_gpkg("lacs_suivis", "Lacs suivis : durée médiane de l'eau libre")
    styler_lacs(lacs)
    tempo = couche_gpkg("eau_libre_lac_annee", "Eau libre par lac et par année (temporel)")
    styler_temporel(tempo)
    mer = couche_gpkg("mer", "Baie et détroit de Dease")
    mer.setRenderer(QgsSingleSymbolRenderer(QgsFillSymbol.createSimple(
        {"color": "0,0,0,0", "outline_color": "#184f95", "outline_width": "0.2"})))
    hameau = couche_gpkg("hameau", "Hameau")
    hameau.setRenderer(QgsSingleSymbolRenderer(QgsMarkerSymbol.createSimple(
        {"name": "circle", "color": "white", "outline_color": "#0b0b0b", "outline_width": "0.5", "size": "2.6"})))
    cadre = couche_gpkg("cadre_bathymetrie", "Zone de bathymétrie")
    cadre.setRenderer(QgsSingleSymbolRenderer(QgsFillSymbol.createSimple(
        {"color": "0,0,0,0", "outline_color": "white", "outline_width": "0.5", "outline_style": "dash"})))
    regime = raster(config.RESULTATS / "glace_regime_2020_40m.tif", "Régime de la glace, avril 2020")
    paletted(regime, [(1, "#c63b3b", "glace flottante"), (2, "#256abf", "glace posée (probable)"),
                      (3, "#c3c2b7", "indéterminé")])
    sdb = raster(config.RESULTATS / "bathymetrie_sdb_10m.tif", "Profondeur Sentinel-2 (m)")
    pseudo(sdb, 0, 15, BLEU, "m")
    classes = raster(config.RESULTATS / "bathymetrie_classes_10m.tif", "Fiabilité optique")
    paletted(classes, [(2, "#c3c2b7", "12 à 15 m, incertain"), (3, "#52514e", "trop profond pour l'optique")])
    disp = raster(config.RESULTATS / "bathymetrie_dispersion_10m.tif", "Dispersion entre passages (m)")
    pseudo(disp, 0, 4, ["#f0efec", "#eb6834"], "m")

    for lyr in (fond, lacs, tempo, mer, hameau, cadre, regime, sdb, classes, disp):
        proj.addMapLayer(lyr, False)
    g = racine.addGroup("Repères")
    for lyr in (hameau, cadre, mer):
        g.addLayer(lyr)
    g = racine.addGroup("Glace des lacs")
    for lyr in (lacs, tempo, regime):
        g.addLayer(lyr)
    g = racine.addGroup("Bathymétrie de la baie")
    for lyr in (classes, sdb, disp):
        g.addLayer(lyr)
    racine.addGroup("Fond").addLayer(fond)
    for lyr in (tempo, regime, disp, mer):
        racine.findLayer(lyr.id()).setItemVisibilityChecked(False)
    return proj, dict(fond=fond, lacs=lacs, hameau=hameau, cadre=cadre)


def mise_en_page(proj, c):
    lay = QgsPrintLayout(proj)
    lay.initializeDefaults()
    lay.setName("Eau libre par lac")
    page = lay.pageCollection().page(0)
    page.setPageSize(QgsLayoutSize(297, 210, QgsUnitTypes.LayoutMillimeters))

    titre = QgsLayoutItemLabel(lay)
    titre.setText("Durée médiane de l'eau libre par lac, 2017-2025")
    titre.setTextFormat(texte(16, True))
    titre.attemptMove(QgsLayoutPoint(12, 8, QgsUnitTypes.LayoutMillimeters))
    titre.attemptResize(QgsLayoutSize(200, 10, QgsUnitTypes.LayoutMillimeters))
    lay.addLayoutItem(titre)
    sous = QgsLayoutItemLabel(lay)
    sous.setText("De la fin de la débâcle (optique Sentinel-2) à la prise consolidée (radar Sentinel-1 et "
                 "optique combinés), médiane des années datées.")
    sous.setTextFormat(texte(9, False, "#52514e"))
    sous.attemptMove(QgsLayoutPoint(12, 18, QgsUnitTypes.LayoutMillimeters))
    sous.attemptResize(QgsLayoutSize(270, 6, QgsUnitTypes.LayoutMillimeters))
    lay.addLayoutItem(sous)

    carte = QgsLayoutItemMap(lay)
    carte.attemptMove(QgsLayoutPoint(12, 26, QgsUnitTypes.LayoutMillimeters))
    x0, y0, x1, y1 = config.EMPRISE
    hauteur = 172
    carte.attemptResize(QgsLayoutSize(hauteur * (x1 - x0) / (y1 - y0), hauteur, QgsUnitTypes.LayoutMillimeters))
    carte.setLayers([c["hameau"], c["cadre"], c["lacs"], c["fond"]])
    carte.setKeepLayerSet(True)
    carte.setCrs(QgsCoordinateReferenceSystem("EPSG:32613"))
    carte.zoomToExtent(QgsRectangle(x0, y0, x1, y1))
    carte.setFrameEnabled(True)
    carte.setFrameStrokeColor(QColor("#c3c2b7"))
    lay.addLayoutItem(carte)

    leg = QgsLayoutItemLegend(lay)
    leg.setTitle("Eau libre (médiane)")
    leg.setLinkedMap(carte)
    leg.setAutoUpdateModel(False)
    arbre = QgsLayerTree()
    arbre.addLayer(c["lacs"]).setName("Lacs suivis")
    leg.model().setRootGroup(arbre)
    leg._arbre = arbre  # garde l'arbre en vie
    leg.rstyle(QgsLegendStyle.Title).setTextFormat(texte(11, True))
    leg.rstyle(QgsLegendStyle.Group).setTextFormat(texte(9, True))
    leg.rstyle(QgsLegendStyle.Subgroup).setTextFormat(texte(9, True))
    leg.rstyle(QgsLegendStyle.SymbolLabel).setTextFormat(texte(8.5))
    leg.attemptMove(QgsLayoutPoint(212, 30, QgsUnitTypes.LayoutMillimeters))
    lay.addLayoutItem(leg)

    eb = QgsLayoutItemScaleBar(lay)
    eb.setStyle("Single Box")
    eb.setLinkedMap(carte)
    eb.setUnits(QgsUnitTypes.DistanceKilometers)
    eb.setUnitLabel("km")
    eb.setUnitsPerSegment(5)   # QGIS convertit lui-même les mètres de la carte en km
    eb.setNumberOfSegments(2)
    eb.setNumberOfSegmentsLeft(0)
    eb.setTextFormat(texte(8))
    eb.attemptMove(QgsLayoutPoint(212, 180, QgsUnitTypes.LayoutMillimeters))
    lay.addLayoutItem(eb)

    nord = QgsLayoutItemPicture(lay)
    nord.setPicturePath(":/images/north_arrows/layout_default_north_arrow.svg")
    nord.attemptMove(QgsLayoutPoint(270, 162, QgsUnitTypes.LayoutMillimeters))
    nord.attemptResize(QgsLayoutSize(10, 14, QgsUnitTypes.LayoutMillimeters))
    lay.addLayoutItem(nord)

    src = QgsLayoutItemLabel(lay)
    src.setText("Projection UTM 13 N (EPSG:32613). Fond : Copernicus Sentinel-2, 7 août 2024. Lacs : "
                "OpenStreetMap. Dates : Sentinel-1, Sentinel-2, Landsat 8 et 9, 2017-2025. "
                "Mise en page : QGIS 3.34.")
    src.setTextFormat(texte(7, False, "#898781"))
    src.attemptMove(QgsLayoutPoint(12, 200, QgsUnitTypes.LayoutMillimeters))
    src.attemptResize(QgsLayoutSize(270, 6, QgsUnitTypes.LayoutMillimeters))
    lay.addLayoutItem(src)

    proj.layoutManager().addLayout(lay)
    ex = QgsLayoutExporter(lay)
    reglages = QgsLayoutExporter.ImageExportSettings()
    reglages.dpi = 150
    r = ex.exportToImage(str(config.FIGURES / "07_eau_libre_lacs.png"), reglages)
    print("export de la mise en page :", "réussi" if r == QgsLayoutExporter.Success else f"code {r}")


# ---------------------------------------------------------------------------
def source_param(nom):
    return QgsProcessingModelChildParameterSource.fromModelParameter(nom)


def source_fixe(v):
    return QgsProcessingModelChildParameterSource.fromStaticValue(v)


def modele_stumpf():
    m = QgsProcessingModelAlgorithm("Rapport de Stumpf (bleu sur vert)", "Cambridge Bay")
    m.setHelpContent({"ALG_DESC": "ln(n R_bleu) / ln(n R_vert), n = 1000, réflectances x 10000 "
                                  "(bande 1 : B02, bande 2 : B03), plancher 0,0001."})
    p = QgsProcessingParameterRasterLayer("scene", "Scène Sentinel-2 (B02, B03, réflectance x 10000)")
    m.addModelParameter(p, QgsProcessingModelParameter("scene"))
    ch = QgsProcessingModelChildAlgorithm("gdal:rastercalculator")
    ch.setChildId("rapport")
    ch.setDescription("Calculatrice raster (GDAL)")
    for k, v in {"INPUT_A": source_param("scene"), "BAND_A": source_fixe(1), "INPUT_B": source_param("scene"),
                 "BAND_B": source_fixe(2),
                 "FORMULA": source_fixe("log(maximum(A,1)*0.1)/log(maximum(B,1)*0.1)"),
                 "RTYPE": source_fixe(5), "NO_DATA": source_fixe(-9999)}.items():
        ch.addParameterSources(k, [v])
    out = QgsProcessingModelOutput("rapport_stumpf", "Rapport bleu sur vert")
    out.setChildOutputName("OUTPUT")
    out.setChildId("rapport")
    ch.setModelOutputs({"rapport_stumpf": out})
    m.addChildAlgorithm(ch)
    m.updateDestinationParameters()
    return m


def modele_radar():
    m = QgsProcessingModelAlgorithm("Médiane radar par lac", "Cambridge Bay")
    m.setHelpContent({"ALG_DESC": "Médiane du sigma0 HH (dB x 100) dans chaque lac érodé de 120 m."})
    m.addModelParameter(QgsProcessingParameterVectorLayer("lacs", "Lacs érodés"),
                        QgsProcessingModelParameter("lacs"))
    m.addModelParameter(QgsProcessingParameterRasterLayer("radar", "Passage Sentinel-1 (dB x 100)"),
                        QgsProcessingModelParameter("radar"))
    ch = QgsProcessingModelChildAlgorithm("native:zonalstatisticsfb")
    ch.setChildId("zonal")
    ch.setDescription("Statistiques de zone")
    for k, v in {"INPUT": source_param("lacs"), "INPUT_RASTER": source_param("radar"),
                 "RASTER_BAND": source_fixe(1), "COLUMN_PREFIX": source_fixe("s1_"),
                 "STATISTICS": source_fixe([0, 3])}.items():
        ch.addParameterSources(k, [v])
    out = QgsProcessingModelOutput("medianes", "Médianes par lac")
    out.setChildOutputName("OUTPUT")
    out.setChildId("zonal")
    ch.setModelOutputs({"medianes": out})
    m.addChildAlgorithm(ch)
    m.updateDestinationParameters()
    return m


def sorties_temporaires(m):
    return {d.name(): "TEMPORARY_OUTPUT" for d in m.destinationParameterDefinitions()}


def controle_croise(m_stumpf, m_radar):
    """Applique les modèles aux mêmes données que la chaîne Python et mesure l'écart."""
    import numpy as np
    import pandas as pd
    from osgeo import gdal
    import processing
    from cbow import bathy

    lignes = []
    fb = QgsProcessingFeedback()
    scenes = sorted((config.DATA / "bathy" / "scenes").glob("*.tif"))
    if scenes:
        s = scenes[0]
        res = processing.run(m_stumpf, {"scene": str(s), **sorties_temporaires(m_stumpf)}, feedback=fb)
        q = gdal.Open(res[m_stumpf.destinationParameterDefinitions()[0].name()]).ReadAsArray().astype("float64")
        a = gdal.Open(str(s)).ReadAsArray().astype("float64")
        bleu, vert = a[0], a[1]
        ok = (bleu != -32768) & (vert != -32768)
        p = bathy.rapport_stumpf(bleu / 10000, vert / 10000)
        v = ok & np.isfinite(p) & np.isfinite(q) & (q != -9999) & (np.abs(p) < 100)
        e = np.abs(q[v] - p[v])
        lignes.append(dict(controle="Rapport de Stumpf, modèle QGIS contre Python", donnees=s.stem,
                           n=int(v.sum()), ecart_max=float(e.max()), ecart_moyen=float(e.mean())))
    s1 = pd.read_csv(config.RESULTATS / "s1_lacs.csv")
    fichiers = sorted((config.DATA / "s1" / "serie_80m").glob("2021-04-*.tif"))
    if fichiers:
        f = fichiers[0]
        date, orb = f.stem.split("_R")
        res = processing.run(m_radar, {"lacs": f"{GPKG}|layername=lacs_suivis_erodes", "radar": str(f),
                                       **sorties_temporaires(m_radar)}, feedback=fb)
        couche = res[m_radar.destinationParameterDefinitions()[0].name()]
        if isinstance(couche, str):
            couche = QgsVectorLayer(couche, "m", "ogr")
        q = {int(ft["lac_id"]): ft["s1_median"] / 100 for ft in couche.getFeatures()
             if ft["s1_median"] is not None}
        py = s1[(s1.date == date) & (s1.orbite == int(orb)) & (s1.objet != "mer")]
        py = {int(o): d for o, d in zip(py.objet, py.db_med)}
        communs = sorted(set(q) & set(py))
        e = np.array([abs(q[k] - py[k]) for k in communs])
        lignes.append(dict(controle="Médiane radar par lac, modèle QGIS contre Python", donnees=f.stem,
                           n=len(communs), ecart_max=float(e.max()), ecart_moyen=float(e.mean())))
    t = pd.DataFrame(lignes)
    t.to_csv(config.RESULTATS / "controle_qgis.csv", index=False, float_format="%.3g")
    print(t.to_string(index=False))


def chemins_relatifs(qgz: Path):
    """Rend relatifs les chemins de secours que la mise en page écrit en absolu."""
    import re
    import zipfile
    tmp = qgz.with_suffix(".tmp")
    motif = re.compile('source="' + re.escape(str(RACINE)) + r'[\\/]([^"]*)"')

    def relatif(m):
        return 'source="../' + m.group(1).replace("\\", "/") + '"'

    with zipfile.ZipFile(qgz) as zin, zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename.endswith(".qgs"):
                data = motif.sub(relatif, data.decode("utf-8")).encode("utf-8")
            zout.writestr(item, data)
    tmp.replace(qgz)


def main():
    app = QgsApplication([], True)
    app.initQgis()
    sys.path.append(str(QGIS_PLUGINS))
    from processing.core.Processing import Processing
    Processing.initialize()

    proj, c = construire_projet()
    mise_en_page(proj, c)
    (Q / "modeles").mkdir(parents=True, exist_ok=True)
    ms, mr = modele_stumpf(), modele_radar()
    ms.toFile(str(Q / "modeles" / "rapport_stumpf.model3"))
    mr.toFile(str(Q / "modeles" / "mediane_radar_lacs.model3"))
    proj.write(str(Q / "cambridge_bay.qgz"))
    chemins_relatifs(Q / "cambridge_bay.qgz")
    print("projet écrit :", Q / "cambridge_bay.qgz")
    controle_croise(ms, mr)
    sys.stdout.flush()
    os._exit(0)   # exitQgis() plante parfois après Processing


if __name__ == "__main__":
    main()
