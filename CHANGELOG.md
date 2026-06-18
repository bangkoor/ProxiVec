# Changelog

## v1.2.0

- Added optional DEM input for 3D distance raster generation.
- Queried elevation values with `QgsRasterDataProvider.identify()` after transforming sample coordinates to the DEM CRS when needed.
- Densified line and polygon geometries before elevation sampling so 3D distance uses more representative target vertices.
- Added DEM resolution warning in the UI for rasters coarser than 30 meters.
- Kept the existing 2D raster proximity workflow unchanged when no DEM is selected.

## v1.1.0

- Renamed UI terminology from target layer to input layer for better clarity.
- Added input layer file browser with last-used directory memory.
- Added help panel with quick guidance and key notes about meter-based output.
- Added manual target CRS selection alongside automatic working CRS detection.
- Improved analysis extent workflow for input extent, layer extent, and polygon bounding box extent.
- Made the dialog non-modal so layers can be added to the project while ProxiVec stays open.
- Improved refresh and compatibility handling for mixed plugin and UI versions.

## v1.0.0

- First release.
- Generated proximity distance raster output in meters from vector targets.
- Added automatic working CRS selection with projected CRS preference and fallbacks.
- Added extent options, target filtering, optional max distance, and output auto-load.
