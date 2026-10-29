# Cambridge Bay open-water window

**Freeze-up, break-up and coastal bathymetry around Iqaluktuuttiaq (Nunavut), 2017-2025, from open satellite data**

A reproducible pipeline that dates, every year, the break-up and freeze-up of 43 lakes and of the bay at Cambridge Bay with three sensors whose blind spots differ (Sentinel-1 radar, Sentinel-2 optical, Landsat thermal), measures what each of them misses, then retrieves the bathymetry of the bay during the open-water window and checks it against the soundings of the Canadian Hydrographic Service.

> Personal research project, without field measurements, built on open data only. Ice dates are validated by agreement between sensors; the bathymetry is not for navigation.

[Version française](README.fr.md), **[Article (PDF, in French, English abstract)](docs/article.pdf)**, [Sources and licences](docs/sources.md)

[![Contrôle](https://github.com/jauresmas/cambridge-bay-open-water/actions/workflows/controle.yml/badge.svg)](https://github.com/jauresmas/cambridge-bay-open-water/actions/workflows/controle.yml)

## In figures

| | |
|---|---:|
| Sentinel-1 EW radar passes, Sentinel-2 optical passes and useful Landsat thermal scenes (2017-2025) | 1,334, 1,079 and 531 |
| Lakes monitored (over 1 km²), plus the bay | 43 |
| Melt on the ice (radar), water at the surface (thermal), end of break-up (optical), medians | 31 May, 22 June, 7 July |
| First ice (thermal), consolidated ice (radar and optical), medians | 23 September, 5 October |
| Freeze-up precision, radar alone then combined with optical | ± 3.2 d, then ± 1.5 d |
| Open water on the lakes, 2017-2022 then 2023-2025 (annual medians) | 83 d, then 106 d |
| Open water in the bay (median) | 111 d, 19 July to 12 November |
| Sentinel-2 bathymetry, mean absolute error between 0 and 20 m (block cross-validation, 8,812 cells) | 2.3 m |
| Depth down to which the map is reliable | 12 m |
| Share of "bedfast" ice read from radar against Stefan thickness (8 winters) | r = -0.74, opposite to the hypothesis |

Each sensor dates a different stage of the same process: thermal sees meltwater on top of the ice weeks before the ice is gone, radar sees wet snow, optical sees the ice disappear. Sensors are combined only when they see the same stage.

## Three questions

1. **Dating the ice.** Can break-up and freeze-up be dated for every lake and for the bay, every year, and how precisely, sensor by sensor and combined?
2. **Seeing the bottom.** During the open-water window, down to what depth and with what error does Sentinel-2 retrieve coastal bathymetry?
3. **Floating or bedfast ice.** Does winter radar separate floating ice from ice frozen to the bottom, and does that share follow the ice thickness given by Stefan's law?

## Three sensors, three stages, three blind spots

![Greiner Lake seen by the three sensors](figures/02_series_greiner.png)

Radar sees all year round but confuses wind-roughened water with wet ice; optical imagery sees open water, but not during the polar night or under clouds; thermal imagery separates water at 0 °C from colder ice, but is rarely cloud-free. Each date is an interval between two observations, and two sensors are combined (by intersecting their intervals) only when they see the same stage: radar and optical for freeze-up.

![Useful observations per month and dating precision](figures/03_angles_morts.png)

## The open-water window

![Break-up and freeze-up calendar](figures/04_calendrier.png)

From one lake to another, open water lasts 76 to 101 days. Large lakes open later but also freeze later, so the duration does not depend on lake size. Map laid out in QGIS:

![Median open-water duration per lake, QGIS layout](figures/07_eau_libre_lacs.png)

## Bathymetry of the bay

![Sentinel-2 bathymetry and NONNA soundings](figures/05_bathymetrie.png)

Three models (Stumpf, Lyzenga, random forest) are compared with a **spatial block cross-validation (1.5 km blocks)**, so that two nearly identical neighbouring cells never end up one in training and the other in testing. The map only shows depths where optics can still tell the bottom from deep water.

## A test that fails, and why

![Radar change between December and April](figures/06_glace_regime.png)

The share of "bedfast" ice read from radar moves opposite to Stefan's ice thickness. Dry land, used as a control, does not move: the early-winter level of the lakes, which varies a lot from year to year, blurs the signal at 90 m resolution. The result is kept and explained in the article rather than discarded.

## Method and tools

1. **Read** images without an account, window by window, on a common UTM 13 N grid (80 m for time series, 40 m for radar maps, 10 m for bathymetry).
2. **Convert** each pass into a physical quantity: calibrated radar σ⁰ normalised to 35° incidence, optical classes (cloud, open water, ice or snow), Landsat surface temperature.
3. **Date** each stage by an interval between two real observations; its half-width measures what the sensor misses.
4. **Combine** two sensors, by intersecting their intervals, only when they see the same stage (radar and optical for freeze-up).
5. **Validate**: bathymetry by spatial block cross-validation on NONNA soundings, bedfast ice against Stefan's law, and two steps of the pipeline rebuilt in QGIS.

| Tool | Version | Use |
|---|---|---|
| Python | 3.10 | processing pipeline (scripts 00 to 11), tests |
| NumPy, pandas, SciPy | 1.26, 2.1, 1.15 | computation, time series, statistics |
| rasterio (GDAL) | 1.4 (GDAL 3.9) | COG reading, radar calibration, reprojection |
| GeoPandas, Shapely, pyproj | 1.1, 2.0, 3.7 | lakes, masks, projections |
| scikit-learn | 1.7 | random forest, cross-validation |
| Matplotlib | 3.8 | article figures |
| **QGIS** (PyQGIS, Processing) | **3.34 LTR** | map project, temporal controller, print layout, graphical modeler |
| pytest | 8.3 | method tests |
| Planetary Computer STAC API | | access to Sentinel and Landsat imagery |

**QGIS project.** Open [`qgis/cambridge_bay.qgz`](qgis/cambridge_bay.qgz) in QGIS 3.34 or later: styled layers in four groups, a temporal layer that animates open water lake by lake (*View > Panels > Temporal Controller*), the "Eau libre par lac" print layout, and two graphical models in [`qgis/modeles/`](qgis/modeles/) (Stumpf ratio with the GDAL raster calculator, radar median per lake with zonal statistics). Run on the same data as the Python pipeline, they give the same result: maximum difference 9 × 10⁻⁷ over 7 million pixels for the ratio, no difference on the 43 lake medians ([`resultats/controle_qgis.csv`](resultats/controle_qgis.csv)). The project is rebuilt by `scripts/11_projet_qgis.py`, run with the QGIS Python.

## Reproduce

Python 3.10 or later. No account is needed: images are read window by window from the Planetary Computer STAC catalogue (about 3 GB in total in `data/`).

```bash
pip install -r requirements.txt
python scripts/run_all.py
```

Scripts `00` to `11` run in order and resume where they stopped (see the table in the [French README](README.fr.md#reproduire)). Methods are tested on synthetic cases, without network access: `python -m pytest`.

## Next steps

Field measurements (MOACC platform, ice drilling, lake soundings), finer radar (RADARSAT Constellation, Sentinel-1C), airborne thermal infrared, hyperspectral imagery to separate water colour from depth, and ICESat-2 lidar calibration where no sounding exists. Details in the [article](docs/article.pdf).
