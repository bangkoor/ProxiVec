import math
import os
import tempfile
from dataclasses import dataclass

import numpy as np
import processing
from osgeo import gdal, osr

from qgis.core import (
    Qgis,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsCsException,
    QgsFeature,
    QgsFeatureRequest,
    QgsGeometry,
    QgsMessageLog,
    QgsPointXY,
    QgsProject,
    QgsRaster,
    QgsRectangle,
    QgsSpatialIndex,
    QgsUnitTypes,
    QgsVectorLayer,
    QgsWkbTypes,
)


@dataclass
class SampledTargetPoint:
    x: float
    y: float
    z: float


@dataclass
class ProximityRunResult:
    output_path: str
    rasterized_path: str
    working_crs: QgsCoordinateReferenceSystem
    analysis_extent: QgsRectangle
    pixel_size: float
    total_target_features: int
    valid_target_features: int
    skipped_target_features: int
    transform_failures: int
    distance_mode: str
    dem_name: str = ""
    sampled_target_points: int = 0


class ProximityEngine:
    LOG_TAG = "ProxiVec"

    def __init__(
        self,
        target_layer,
        pixel_size,
        output_path,
        target_expression="",
        target_selected_only=False,
        analysis_extent=None,
        analysis_extent_crs=None,
        max_distance=None,
        working_crs_override=None,
        dem_layer=None,
        log_initial_state=True,
    ):
        self.target_layer = target_layer
        self.pixel_size = float(pixel_size)
        self.output_path = output_path
        self.target_expression = (target_expression or "").strip()
        self.target_selected_only = target_selected_only
        self.analysis_extent = analysis_extent
        self.analysis_extent_crs = analysis_extent_crs
        self.max_distance = float(max_distance) if max_distance else None
        self.working_crs_override = working_crs_override
        self.dem_layer = dem_layer if dem_layer is not None and dem_layer.isValid() else None

        self.working_crs, self.working_crs_reason = self._resolve_working_crs()
        self.target_transform = QgsCoordinateTransform(
            self.target_layer.crs(), self.working_crs, QgsProject.instance()
        )
        self.transform_to_dem_crs = None
        if self.dem_layer is not None and self.dem_layer.crs() != self.working_crs:
            self.transform_to_dem_crs = QgsCoordinateTransform(
                self.working_crs, self.dem_layer.crs(), QgsProject.instance()
            )
        self.dem_resolution = self._resolve_dem_resolution_meters()

        self.total_target_features = 0
        self.valid_target_features = 0
        self.skipped_target_features = 0
        self.transform_failures = 0

        if log_initial_state:
            self._log(
                "Working CRS: {} - {}".format(
                    self._crs_label(self.working_crs), self.working_crs_reason
                )
            )

            if self.target_layer.crs() != self.working_crs:
                self._log(
                    "Target CRS ({}) will be reprojected to working CRS ({}) before "
                    "rasterization.".format(
                        self._crs_label(self.target_layer.crs()),
                        self._crs_label(self.working_crs),
                    ),
                    Qgis.Warning,
                )

            if self.dem_layer is not None:
                self._log(
                    "DEM layer enabled for 3D distance: {}".format(self.dem_layer.name())
                )
                if self.dem_layer.crs() != self.working_crs:
                    self._log(
                        "DEM CRS ({}) will be queried using transformed coordinates "
                        "from working CRS ({}).".format(
                            self._crs_label(self.dem_layer.crs()),
                            self._crs_label(self.working_crs),
                        )
                    )
                if self.dem_resolution is not None:
                    self._log(
                        f"DEM resolution: {self.dem_resolution:.3f} meters per pixel."
                    )

    def compute(self, feedback=None):
        if feedback:
            feedback.setProgress(0)
            feedback.pushInfo("Starting proximity raster generation...")

        if self.pixel_size <= 0:
            raise ValueError("Pixel size must be greater than 0.")
        if not self.output_path:
            raise ValueError("Output raster path is required.")

        if not self._is_metric_projected(self.working_crs):
            raise ValueError(
                "Working CRS must be projected with meter units to ensure distance output is in meters."
            )

        output_dir = os.path.dirname(self.output_path)
        if output_dir and not os.path.isdir(output_dir):
            raise ValueError("Output folder was not found.")

        if feedback:
            feedback.setProgress(5)
            feedback.pushInfo("Collecting target features...")

        target_features = self._collect_features(
            self.target_layer, self.target_expression, self.target_selected_only
        )
        self.total_target_features = len(target_features)
        if not target_features:
            raise ValueError("No target features matched the filter.")

        if feedback:
            feedback.setProgress(20)
            feedback.pushInfo("Reprojecting target features to working CRS...")

        prepared_layer = self._build_prepared_layer(target_features)
        if prepared_layer.featureCount() == 0:
            raise ValueError("All target features failed transformation or were empty.")

        self.valid_target_features = prepared_layer.featureCount()
        if feedback:
            feedback.setProgress(45)
            feedback.pushInfo("Resolving analysis extent...")

        analysis_extent = self._resolve_analysis_extent(prepared_layer)
        if feedback:
            feedback.setProgress(55)
        distance_mode = "2D"
        dem_name = ""
        sampled_target_points = 0
        rasterized_path = ""

        if self.dem_layer is None:
            if feedback:
                feedback.pushInfo("Rasterizing target layer...")

            rasterized_path = self._rasterize_targets(
                prepared_layer, analysis_extent, feedback=feedback
            )
            if feedback:
                feedback.setProgress(75)
                feedback.pushInfo("Computing proximity raster...")

            self._run_proximity(rasterized_path, feedback=feedback)
        else:
            if feedback:
                feedback.pushInfo("Sampling target geometry elevations from DEM...")
                feedback.setProgress(65)

            sampled_targets, target_index = self._build_target_samples(prepared_layer)
            sampled_target_points = len(sampled_targets)
            if sampled_target_points == 0:
                raise ValueError(
                    "No valid DEM elevation samples were found on the target geometries."
                )

            if feedback:
                feedback.pushInfo("Computing 3D proximity raster from DEM samples...")
                feedback.setProgress(75)

            self._run_3d_proximity(
                analysis_extent, sampled_targets, target_index, feedback=feedback
            )
            distance_mode = "3D"
            dem_name = self.dem_layer.name()

        if feedback:
            feedback.setProgress(95)
            feedback.pushInfo("Finalizing output...")

        return ProximityRunResult(
            output_path=self.output_path,
            rasterized_path=rasterized_path,
            working_crs=self.working_crs,
            analysis_extent=analysis_extent,
            pixel_size=self.pixel_size,
            total_target_features=self.total_target_features,
            valid_target_features=self.valid_target_features,
            skipped_target_features=self.skipped_target_features,
            transform_failures=self.transform_failures,
            distance_mode=distance_mode,
            dem_name=dem_name,
            sampled_target_points=sampled_target_points,
        )

    def build_summary(self, result):
        extent_text = (
            f"{result.analysis_extent.xMinimum():.3f}, "
            f"{result.analysis_extent.xMaximum():.3f}, "
            f"{result.analysis_extent.yMinimum():.3f}, "
            f"{result.analysis_extent.yMaximum():.3f}"
        )
        lines = [
            "ProxiVec completed.",
            f"Raster output: {result.output_path}",
            f"Working CRS: {self._crs_label(result.working_crs)}",
            f"Working CRS reason: {self.working_crs_reason}",
            f"Pixel size: {result.pixel_size}",
            f"Analysis extent: {extent_text}",
            f"Valid targets: {result.valid_target_features}/{result.total_target_features}",
            f"Distance mode: {result.distance_mode}",
            "Distance units: meters (georeferenced units in the working CRS)",
        ]
        if result.rasterized_path:
            lines.append(f"Intermediate target mask: {result.rasterized_path}")
        if result.dem_name:
            lines.append(f"DEM layer: {result.dem_name}")
        if result.sampled_target_points:
            lines.append(f"Sampled target points: {result.sampled_target_points}")
        if result.skipped_target_features:
            lines.append(f"Skipped targets: {result.skipped_target_features}")
        if result.transform_failures:
            lines.append(f"Transform failures: {result.transform_failures}")
        return "\n".join(lines)

    def _resolve_working_crs(self):
        if self._is_metric_projected(self.working_crs_override):
            return self.working_crs_override, "using user-selected target CRS"

        project_crs = QgsProject.instance().crs()
        if self._is_metric_projected(project_crs):
            return project_crs, "using QGIS project CRS"

        target_crs = self.target_layer.crs()
        if self._is_metric_projected(target_crs):
            return target_crs, "using target layer CRS"

        utm_crs = self.get_utm_crs_from_extent(
            self.target_layer.extent(), self.target_layer.crs()
        )
        if self._is_metric_projected(utm_crs):
            return utm_crs, "auto-selected UTM from target layer extent"

        fallback = QgsCoordinateReferenceSystem("EPSG:3857")
        return fallback, "fallback to EPSG:3857"

    def _collect_features(self, layer, expression, selected_only):
        request = QgsFeatureRequest()
        if expression:
            request.setFilterExpression(expression)

        selected_ids = set(layer.selectedFeatureIds()) if selected_only else None
        features = []
        for feature in layer.getFeatures(request):
            if selected_ids is not None and feature.id() not in selected_ids:
                continue
            features.append(QgsFeature(feature))
        return features

    def _build_prepared_layer(self, features):
        geometry_name = QgsWkbTypes.displayString(QgsWkbTypes.flatType(self.target_layer.wkbType()))
        crs_token = self.working_crs.authid() or self.working_crs.toWkt()
        prepared_layer = QgsVectorLayer(
            f"{geometry_name}?crs={crs_token}",
            "proxivec_target_working",
            "memory",
        )
        provider = prepared_layer.dataProvider()
        provider.addAttributes(self.target_layer.fields())
        prepared_layer.updateFields()

        prepared_features = []
        for feature in features:
            geometry = feature.geometry()
            if not geometry or geometry.isEmpty():
                self.skipped_target_features += 1
                self._log(
                    f"Target FID {feature.id()} skipped due to empty geometry.",
                    Qgis.Warning,
                )
                continue

            reprojected = self._reproject(
                geometry, self.target_transform, f"target FID {feature.id()}"
            )
            if reprojected is None or reprojected.isEmpty():
                self.skipped_target_features += 1
                continue

            prepared_feature = QgsFeature(prepared_layer.fields())
            prepared_feature.setGeometry(reprojected)
            prepared_feature.setAttributes(feature.attributes())
            prepared_features.append(prepared_feature)

        provider.addFeatures(prepared_features)
        prepared_layer.updateExtents()
        return prepared_layer

    def _resolve_analysis_extent(self, prepared_layer):
        if self.analysis_extent is not None:
            extent = QgsRectangle(self.analysis_extent)
            extent_crs = self.analysis_extent_crs or self.target_layer.crs()
            if extent_crs != self.working_crs:
                try:
                    transform = QgsCoordinateTransform(
                        extent_crs, self.working_crs, QgsProject.instance()
                    )
                    extent = transform.transformBoundingBox(extent)
                except QgsCsException as exc:
                    raise ValueError(
                        f"Failed to transform analysis extent to working CRS: {exc}"
                    )
        else:
            extent = QgsRectangle(prepared_layer.extent())

        if extent.isEmpty():
            raise ValueError("Analysis extent is empty.")

        return self._normalize_extent(extent)

    def _normalize_extent(self, extent):
        rect = QgsRectangle(extent)
        half_size = max(self.pixel_size * 5.0, 1.0)

        if rect.width() == 0:
            rect.setXMinimum(rect.xMinimum() - half_size)
            rect.setXMaximum(rect.xMaximum() + half_size)
        if rect.height() == 0:
            rect.setYMinimum(rect.yMinimum() - half_size)
            rect.setYMaximum(rect.yMaximum() + half_size)
        if rect.width() < self.pixel_size:
            center_x = rect.center().x()
            rect.setXMinimum(center_x - self.pixel_size / 2.0)
            rect.setXMaximum(center_x + self.pixel_size / 2.0)
        if rect.height() < self.pixel_size:
            center_y = rect.center().y()
            rect.setYMinimum(center_y - self.pixel_size / 2.0)
            rect.setYMaximum(center_y + self.pixel_size / 2.0)

        return rect

    def _rasterize_targets(self, prepared_layer, analysis_extent, feedback=None):
        temp_dir = tempfile.mkdtemp(prefix="proxivec_")
        rasterized_path = os.path.join(temp_dir, "target_mask.tif")

        params = {
            "INPUT": prepared_layer,
            "FIELD": None,
            "BURN": 1,
            "USE_Z": False,
            "UNITS": 1,
            "WIDTH": self.pixel_size,
            "HEIGHT": self.pixel_size,
            "EXTENT": self._extent_string(analysis_extent, self.working_crs),
            "NODATA": 0,
            "OPTIONS": "",
            "DATA_TYPE": 0,
            "INIT": 0,
            "INVERT": False,
            "EXTRA": "",
            "OUTPUT": rasterized_path,
        }
        processing.run("gdal:rasterize", params, feedback=feedback)
        self._log(f"Target mask raster created: {rasterized_path}")
        return rasterized_path

    def _run_proximity(self, rasterized_path, feedback=None):
        proximity_params = {
            "INPUT": rasterized_path,
            "BAND": 1,
            "VALUES": "1",
            "UNITS": 0,
            "MAX_DISTANCE": self.max_distance if self.max_distance else 0,
            "REPLACE": 0,
            "NODATA": -9999,
            "OPTIONS": "",
            "DATA_TYPE": 5,
            "EXTRA": "",
            "OUTPUT": self.output_path,
        }
        processing.run("gdal:proximity", proximity_params, feedback=feedback)
        self._log(f"Proximity raster created: {self.output_path}")

    def _build_target_samples(self, prepared_layer):
        sampled_targets = {}
        target_index = QgsSpatialIndex()
        sample_id = 0
        interval = self._sampling_interval()

        for feature in prepared_layer.getFeatures():
            geometry = feature.geometry()
            if geometry is None or geometry.isEmpty():
                continue

            sample_geometry = self._geometry_for_sampling(geometry, interval)
            for vertex in sample_geometry.vertices():
                elevation = self.get_elevation(
                    vertex.x(), vertex.y(), self.dem_layer, self.transform_to_dem_crs
                )
                if elevation is None:
                    continue

                sample_point = SampledTargetPoint(
                    x=vertex.x(),
                    y=vertex.y(),
                    z=elevation,
                )
                sampled_targets[sample_id] = sample_point

                index_feature = QgsFeature()
                index_feature.setId(sample_id)
                index_feature.setGeometry(
                    QgsGeometry.fromPointXY(QgsPointXY(sample_point.x, sample_point.y))
                )
                target_index.addFeature(index_feature)
                sample_id += 1

        self._log(
            f"Prepared {len(sampled_targets)} sampled target points for 3D distance."
        )
        return sampled_targets, target_index

    def _geometry_for_sampling(self, geometry, interval):
        geometry_copy = QgsGeometry(geometry)
        geometry_type = QgsWkbTypes.geometryType(geometry_copy.wkbType())
        if geometry_type == QgsWkbTypes.PointGeometry:
            return geometry_copy

        densified = geometry_copy.densifyByDistance(max(interval, 0.001))
        return densified if densified is not None and not densified.isEmpty() else geometry_copy

    def _sampling_interval(self):
        if self.dem_resolution is not None and self.dem_resolution > 0:
            return max(min(self.pixel_size, self.dem_resolution), 0.001)
        return max(self.pixel_size, 0.001)

    def _run_3d_proximity(self, analysis_extent, sampled_targets, target_index, feedback=None):
        nodata_value = -9999.0
        width = max(1, int(math.ceil(analysis_extent.width() / self.pixel_size)))
        height = max(1, int(math.ceil(analysis_extent.height() / self.pixel_size)))

        driver = gdal.GetDriverByName("GTiff")
        dataset = driver.Create(
            self.output_path,
            width,
            height,
            1,
            gdal.GDT_Float32,
            options=["COMPRESS=LZW"],
        )
        if dataset is None:
            raise ValueError("Failed to create output raster.")

        try:
            dataset.SetGeoTransform(
                (
                    analysis_extent.xMinimum(),
                    self.pixel_size,
                    0.0,
                    analysis_extent.yMaximum(),
                    0.0,
                    -self.pixel_size,
                )
            )
            spatial_ref = osr.SpatialReference()
            spatial_ref.ImportFromWkt(self.working_crs.toWkt())
            dataset.SetProjection(spatial_ref.ExportToWkt())

            band = dataset.GetRasterBand(1)
            band.SetNoDataValue(nodata_value)

            for row in range(height):
                row_values = np.full((1, width), nodata_value, dtype=np.float32)
                y = analysis_extent.yMaximum() - ((row + 0.5) * self.pixel_size)

                for col in range(width):
                    x = analysis_extent.xMinimum() + ((col + 0.5) * self.pixel_size)
                    cell_elevation = self.get_elevation(
                        x, y, self.dem_layer, self.transform_to_dem_crs
                    )
                    if cell_elevation is None:
                        continue

                    query_point = QgsPointXY(x, y)
                    nearest_ids = target_index.nearestNeighbor(query_point, 1)
                    if not nearest_ids:
                        continue

                    nearest_sample = sampled_targets[nearest_ids[0]]
                    best_2d = math.hypot(x - nearest_sample.x, y - nearest_sample.y)
                    best_3d = math.sqrt(
                        (best_2d * best_2d)
                        + ((cell_elevation - nearest_sample.z) ** 2)
                    )

                    search_radius = max(best_3d, self.pixel_size)
                    search_area = QgsRectangle(
                        x - search_radius,
                        y - search_radius,
                        x + search_radius,
                        y + search_radius,
                    )
                    candidate_ids = target_index.intersects(search_area) or nearest_ids

                    for candidate_id in candidate_ids:
                        sample_point = sampled_targets[candidate_id]
                        dist_2d = math.hypot(x - sample_point.x, y - sample_point.y)
                        if dist_2d > best_3d:
                            continue

                        dist_3d = math.sqrt(
                            (dist_2d * dist_2d)
                            + ((cell_elevation - sample_point.z) ** 2)
                        )
                        if dist_3d < best_3d:
                            best_3d = dist_3d

                    if self.max_distance is not None and best_3d > self.max_distance:
                        continue

                    row_values[0, col] = best_3d

                band.WriteArray(row_values, xoff=0, yoff=row)

                if feedback and height > 0:
                    progress = 75 + int(((row + 1) / height) * 20)
                    feedback.setProgress(min(progress, 95))

            band.FlushCache()
            dataset.FlushCache()
        finally:
            dataset = None

        self._log(f"3D proximity raster created: {self.output_path}")

    def _reproject(self, geometry, transform, feature_label):
        geom_clone = QgsGeometry(geometry)
        try:
            geom_clone.transform(transform)
        except QgsCsException as exc:
            self.transform_failures += 1
            self._log(
                f"Transform failed for {feature_label}; feature skipped. Detail: {exc}",
                Qgis.Warning,
            )
            return None
        return geom_clone

    def _resolve_dem_resolution_meters(self):
        if self.dem_layer is None:
            return None

        dem_crs = self.dem_layer.crs()
        if not self._is_metric_projected(dem_crs):
            return None

        x_res = abs(self.dem_layer.rasterUnitsPerPixelX())
        y_res = abs(self.dem_layer.rasterUnitsPerPixelY())
        resolution = max(x_res, y_res)
        return resolution if resolution > 0 else None

    @staticmethod
    def get_elevation(x, y, dem_layer, transform_to_dem_crs):
        if dem_layer is None or not dem_layer.isValid():
            return None

        point = QgsPointXY(x, y)
        if transform_to_dem_crs is not None:
            try:
                point = transform_to_dem_crs.transform(point)
            except QgsCsException:
                return None

        identify_result = dem_layer.dataProvider().identify(
            point, QgsRaster.IdentifyFormatValue
        )
        if not identify_result.isValid():
            return None

        values = identify_result.results()
        if not values:
            return None

        elevation = values.get(1)
        if elevation is None and values:
            elevation = next(iter(values.values()))
        if elevation is None:
            return None

        try:
            elevation = float(elevation)
        except (TypeError, ValueError):
            return None

        if math.isnan(elevation):
            return None
        return elevation

    @staticmethod
    def get_utm_crs_from_extent(extent, source_crs):
        if not extent or extent.isEmpty() or not source_crs.isValid():
            return None

        centroid = QgsGeometry.fromPointXY(extent.center())
        wgs84 = QgsCoordinateReferenceSystem("EPSG:4326")

        try:
            transform = QgsCoordinateTransform(source_crs, wgs84, QgsProject.instance())
            centroid.transform(transform)
        except QgsCsException:
            return None

        point = centroid.asPoint()
        lon = point.x()
        lat = point.y()
        zone = max(1, min(60, int((lon + 180) / 6) + 1))
        epsg_code = 32600 + zone if lat >= 0 else 32700 + zone
        return QgsCoordinateReferenceSystem(f"EPSG:{epsg_code}")

    @staticmethod
    def _extent_string(extent, crs):
        crs_token = crs.authid() or crs.toWkt()
        return (
            f"{extent.xMinimum()},{extent.xMaximum()},"
            f"{extent.yMinimum()},{extent.yMaximum()} [{crs_token}]"
        )

    @staticmethod
    def _is_metric_projected(crs):
        return (
            crs is not None
            and crs.isValid()
            and not crs.isGeographic()
            and crs.mapUnits() == QgsUnitTypes.DistanceMeters
        )

    @staticmethod
    def _crs_label(crs):
        if crs is None or not crs.isValid():
            return "Invalid CRS"

        if crs.authid():
            return f"{crs.authid()} ({crs.description()})"
        return crs.description() or "Unnamed CRS"

    def _log(self, message, level=Qgis.Info):
        QgsMessageLog.logMessage(message, self.LOG_TAG, level)
