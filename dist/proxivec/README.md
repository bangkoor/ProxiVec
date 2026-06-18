# ProxiVec — Raster Proximity (QGIS Plugin)

ProxiVec is a QGIS 3.x plugin to generate a **proximity (distance) raster** from a **vector target layer**, similar to **GDAL/QGIS “Proximity (raster distance)”**.

It automatically selects a **projected working CRS** (meters), reprojects the target features, rasterizes them, and computes a distance surface where each pixel stores the **distance to the nearest target feature in meters**.

## Key Features

- **Distance output in meters**
  - Uses a projected working CRS with meter units.
  - Proximity computation uses **georeferenced distance units** (not pixel units).
- **CRS auto-detection**
  - Prefers project CRS if projected (meters).
  - Falls back to target layer CRS if projected (meters).
  - If geographic, auto-selects a UTM CRS from layer extent, and finally falls back to EPSG:3857.
- **Flexible analysis extent**
  - Target layer extent
  - Current canvas extent
  - Calculate from another layer extent (vector/raster)
  - Use polygon layer bounding box (optionally only selected polygons)
- **Filtering**
  - Target expression (QGIS expression)
  - Target selected features only
- **Friendly UI**
  - Optional max distance
  - Progress bar with status text
  - Option to auto-load the output raster into the project

## Output

- **GeoTIFF proximity raster** (`.tif`)
- Pixel values represent **distance to the nearest target** in **meters**

## Requirements

- QGIS **3.22+** (tested with QGIS 3.44 LTR)
- GDAL Processing provider enabled (QGIS Processing)
  - Uses `gdal:rasterize` and `gdal:proximity`

## Installation (Manual)

1. Close QGIS.
2. Copy the plugin folder into your QGIS profile plugins directory:

   Windows (default profile):
   ```text
   %APPDATA%\QGIS\QGIS3\profiles\default\python\plugins\proxivec
   ```

3. Open QGIS → `Plugins` → `Manage and Install Plugins…` → enable **ProxiVec**.

## Where to Find It in QGIS

- Menu: `Vector` → `ProxiVec` → `Proximity Analysis`
- Or toolbar icon (if enabled by QGIS)

## How to Use

1. Open the tool: `Vector` → `ProxiVec` → `Proximity Analysis`
2. Choose:
   - **Target layer**
   - Optional: **Target expression**
   - Optional: **Use selected features only (target layer)**
3. Select **Analysis extent**
   - If using polygon extent, select the polygon layer in “Polygon extent layer”
   - Optional: “Use selected features only” to use bounding box of selected features only
4. Set:
   - **Pixel size (meters)**
   - Optional: **Max distance (meters)**
5. Choose **Output raster** path (`.tif`)
6. Click **Run**

If “Load output raster into the project after completion” is enabled, the resulting GeoTIFF will be added to the map automatically.

## Notes on Accuracy

- Best accuracy is achieved with an appropriate local projected CRS (e.g., UTM zone for your area).
- If your input data is geographic (degrees), ProxiVec will reproject to a projected working CRS before processing.
- Output distances are computed in the working CRS and stored in meters.

## Troubleshooting

- **Output distances look wrong**
  - Check the “Working CRS” section in the dialog.
  - Prefer a local projected CRS for your project.
- **Tool fails with GDAL/Processing errors**
  - Ensure `Processing` is enabled and the GDAL provider is available:
    - QGIS → `Processing` → `Toolbox` should list GDAL algorithms.
- **Polygon extent option still uses target extent**
  - Make sure “Analysis extent” is set to “Use polygon layer (bounding box)”
  - Select a polygon layer in “Polygon extent layer”
  - If “Use selected features only” is checked, ensure the polygons are selected

## Author

- **Arif K Wijayanto**
- Divisi Analisis Lingkungan dan Geospasial Modeling, IPB University
- Email: **akwijayanto@apps.ipb.ac.id**

## License

Add your preferred license here (e.g., GPL-2.0-or-later to match common QGIS plugin licensing).

