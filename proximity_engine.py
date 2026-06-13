import os
import tempfile
from dataclasses import dataclass

import processing

from qgis.core import (
    Qgis,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsCsException,
    QgsFeature,
    QgsFeatureRequest,
    QgsGeometry,
    QgsMessageLog,
    QgsProject,
    QgsRectangle,
    QgsUnitTypes,
    QgsVectorLayer,
    QgsWkbTypes,
)


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

        self.working_crs, self.working_crs_reason = self._resolve_working_crs()
        self.target_transform = QgsCoordinateTransform(
            self.target_layer.crs(), self.working_crs, QgsProject.instance()
        )

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
            feedback.pushInfo("Rasterizing target layer...")

        rasterized_path = self._rasterize_targets(
            prepared_layer, analysis_extent, feedback=feedback
        )
        if feedback:
            feedback.setProgress(75)
            feedback.pushInfo("Computing proximity raster...")

        self._run_proximity(rasterized_path, feedback=feedback)
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
            "Distance units: meters (georeferenced units in the working CRS)",
        ]
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
