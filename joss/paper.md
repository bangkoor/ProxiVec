---
title: "ProxiVec: Raster proximity analysis from vector targets in QGIS with automatic projected CRS selection"
tags:
  - QGIS
  - GIS
  - Python
  - raster
  - proximity
  - distance
  - GDAL
authors:
  - name: Arif K Wijayanto
    orcid: 0000-0003-4581-6065
    affiliation: 1
affiliations:
  - name: Department of Forests Resources Conservation and Ecotourism, Faculty of Forestry and Environment, IPB University, Indonesia, 16680
    index: 1
date: 15 July 2026
bibliography: paper.bib
---

# Summary

Many environmental and spatial-planning analyses need to know how far every location in a study area is from a set of mapped features, such as roads, rivers, settlements, or protected-area boundaries. `ProxiVec` is a plugin for QGIS 3, a free and open-source geographic information system, that turns a vector layer of such features into a raster in which every pixel stores its distance, in meters, to the nearest feature. The plugin automatically chooses a suitable projected coordinate reference system (CRS) before measuring distance, so that results are not silently distorted when the input data are stored in geographic (latitude/longitude) coordinates. `ProxiVec` also offers an optional mode that incorporates elevation from a digital elevation model (DEM), producing straight-line, three-dimensional distances that account for terrain relief rather than flat, two-dimensional distances alone. The result is a single-dialog workflow that produces a ready-to-use GeoTIFF proximity raster for use in downstream modelling, mapping, and spatial statistics.

# Statement of need

Distance-to-feature rasters are a common input for accessibility analysis, risk and exposure modelling, habitat and landscape metrics, and species distribution modelling. In QGIS, producing such a raster with correct, georeferenced distance units typically requires the user to manually chain together several separate steps and providers: choosing or reprojecting to a projected CRS, rasterizing the vector target layer, and running a raster proximity algorithm from GDAL [@gdal] via QGIS's Processing framework [@qgis]. If a suitable projected CRS is not selected before this chain of operations, the resulting "distances" are computed in degrees rather than meters, a mistake that is common among students and applied researchers and that is not obviously flagged by the underlying tools. In addition, none of the existing 2D proximity tools bundled with QGIS or GDAL account for elevation, even though many research questions (for example, visibility, radio or acoustic propagation, and access cost over hilly terrain) depend on the true, terrain-aware separation between two points rather than their planimetric separation alone. `ProxiVec` is intended for researchers, students, and practitioners in environmental science, conservation, and spatial planning who need a reproducible, meter-correct proximity raster without manually orchestrating multiple Processing algorithms, and who sometimes also need a first-order correction for elevation difference that a purely 2D proximity raster cannot provide.

![Workflow comparison for generating a raster proximity map in QGIS without `ProxiVec` (manual, multi-step chaining of CRS preparation, rasterization, and proximity computation) versus with `ProxiVec` (single-dialog workflow with automatic projected CRS selection).\label{fig:workflow}](figure1.png)

# State of the field

Proximity or "distance-to-nearest-feature" rasters can already be produced in QGIS by chaining GDAL's `gdal:rasterize` and `gdal:proximity` algorithms [@gdal] by hand, but this requires the user to separately verify and manage CRS units, which is a frequent source of error. In ArcGIS, the comparable and more automated tools are the (now deprecated) Euclidean Distance tool and its successor, Distance Accumulation [@esri_distance], which additionally support cost-weighted and terrain-aware accumulated-surface distance through cost surfaces and vertical/horizontal factors. Within the free and open-source ecosystem, GRASS GIS's `r.cost` and `r.walk` modules [@grass], and SAGA GIS's accumulated-cost tools [@saga] (both accessible from QGIS through their respective Processing providers) offer conceptually similar cost-accumulation functionality. These tools, however, solve a different analytical problem: they compute accumulated movement cost or effort along a friction/cost surface, which requires the user to supply and parameterize a cost raster, and they are not designed as a guided, single-step proximity workflow starting from a vector layer. Extending `r.cost`, `r.walk`, or the GDAL proximity primitive to also offer CRS-safe, one-step vector-to-raster proximity with an optional straight-line elevation correction would conflate two distinct distance concepts (accumulated cost versus straight-line distance) within tools whose APIs and user expectations are already built around the former. `ProxiVec` was therefore built as a focused, standalone plugin that wraps and automates the existing, well-tested GDAL rasterization and proximity primitives for the 2D case, and adds a new, purpose-built 3D straight-line distance mode, rather than being contributed as a variant mode to the existing cost-accumulation tools.

# Software design

`ProxiVec`'s design centers on removing CRS-related error while staying close to the existing GDAL/QGIS proximity primitives it depends on. The working CRS is resolved through an explicit, documented precedence order: a user override, then the QGIS project CRS, then the target layer's own CRS, then a UTM zone automatically derived from the layer's extent, with EPSG:3857 as a final fallback; at every stage the plugin verifies that the candidate CRS is projected and expressed in meters before accepting it. This precedence was chosen to minimize the number of decisions an applied user must make while still allowing full manual control when needed. For the 2D case, `ProxiVec` deliberately reuses QGIS's Processing framework to call GDAL's `gdal:rasterize` and `gdal:proximity` algorithms rather than reimplementing rasterization or distance-transform logic, since these primitives are already extensively tested and maintained upstream. For the 3D case, no existing GDAL or QGIS primitive computes, per output cell, the nearest feature in three dimensions using externally supplied elevation; `ProxiVec` therefore samples DEM elevation at densified target-geometry vertices, indexes these samples with a spatial index, and performs a bounded nearest-neighbor search per output cell using direct GDAL/NumPy [@numpy] raster writing. This 3D mode is intentionally scoped to straight-line (slant) distance rather than full terrain-following accumulated-cost distance, so that its output remains directly comparable to, and a simple superset of, the 2D mode, and so that users are not required to construct or parameterize a cost surface simply to obtain an elevation-aware distance estimate.

# Research impact statement

`ProxiVec` has been used by the author's research group, the Divisi Analisis Lingkungan dan Geospasial Modeling at IPB University, to generate proximity predictor rasters for a maximum-entropy (MaxEnt) risk model of forestry-crime threat, where distance to access routes and settlements is a standard covariate. The plugin is also listed on the official QGIS Plugin Repository, where installation and download activity are tracked independently of the author, giving an ongoing, third-party signal of uptake within the broader QGIS user community beyond the author's own use. As an early-stage, single-author project, `ProxiVec` does not yet have a track record of external citations or multi-institution adoption; continued public development, together with feedback from users of the QGIS Plugin Repository release, is expected to build this evidence over time.

# AI usage disclosure

Generative AI tools, specifically Claude (Anthropic) and Trae, were used during the development of `ProxiVec` to assist with drafting and refactoring portions of the plugin's source code (including the DEM-based 3D distance routine), drafting supporting documentation (README.md), and drafting this manuscript, including background research comparing `ProxiVec` to related distance-analysis tools. All AI-assisted code, documentation, and text were reviewed, tested, and validated by the author, who made all core design decisions, including the CRS-selection precedence, the scope and algorithm of the 3D distance mode, and the comparative claims made in the State of the field section above.

# References