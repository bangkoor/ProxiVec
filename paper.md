---
title: "ProxiVec: Raster proximity analysis from vector targets in QGIS with automatic projected CRS selection"
tags:
  - QGIS
  - GIS
  - raster
  - proximity
  - distance
  - GDAL
authors:
  - name: Arif K Wijayanto
    affiliation: 1
affiliations:
  - name: Divisi Analisis Lingkungan dan Geospasial Modeling, IPB University, Indonesia
    index: 1
date: 2026-07-15
bibliography: paper.bib
---

# Summary

ProxiVec is a QGIS 3 plugin for generating a raster proximity (distance-to-nearest-target) surface from a vector layer. The plugin automates a workflow commonly used in environmental modelling and spatial planning by (1) selecting an appropriate projected working coordinate reference system (CRS) with meter units, (2) reprojecting and rasterizing target features, and (3) computing a distance raster whose pixel values represent georeferenced distances in meters, consistent with QGIS and GDAL proximity tools [@qgis; @gdal]. ProxiVec optionally supports a 3D distance mode that incorporates elevation from a user-provided DEM.

# Statement of need

Distance-to-feature rasters are a basic input for many analyses (e.g., accessibility, risk and exposure modelling, landscape metrics). In QGIS, producing a Euclidean distance raster typically requires stitching together several steps (CRS preparation, rasterization, and proximity computation) across different tools/providers, rather than a single guided operation comparable to ArcGIS workflows. In practice, many QGIS users also work with geographic (degree-based) data, which can lead to incorrect distance units if a suitable projected CRS is not chosen before running a proximity algorithm. ProxiVec reduces these sources of friction and error by automatically selecting a projected working CRS (preferring the project CRS, then the layer CRS, then an extent-derived UTM zone, with a safe fallback) and by exposing common controls for extent and filtering directly in a single dialog. The result is a reproducible, meter-based proximity raster workflow for QGIS projects.

# Implementation

In 2D mode, ProxiVec uses QGIS Processing to call GDAL algorithms for rasterization and proximity [@gdal], while ensuring that all operations occur in a projected CRS with meter units. Users can define the analysis extent from the input layer, the current map canvas, another layer, or a polygon bounding box, and can filter target features using a QGIS expression or selected features only. The output is a GeoTIFF proximity raster with pixel values stored as floating-point distances.

In 3D mode, ProxiVec samples elevations from a DEM at densified target geometry vertices and then computes per-cell 3D distance as the Euclidean distance combining planimetric distance and elevation difference. Numerical operations for the raster write process rely on NumPy [@numpy].

# Availability

- Source code: https://github.com/bangkoor/ProxiVec
- Operating system: Cross-platform (QGIS 3.x)
- License: GNU General Public License v2.0 or later (GPL-2.0-or-later)
