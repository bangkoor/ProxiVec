import os

from PyQt5 import uic
from PyQt5.QtCore import QObject, Qt, pyqtSignal
from PyQt5.QtWidgets import QFileDialog, QDialog, QDialogButtonBox, QMessageBox

from qgis.core import (
    Qgis,
    QgsMapLayerType,
    QgsMessageLog,
    QgsProcessingFeedback,
    QgsProject,
    QgsSettings,
    QgsVectorLayer,
    QgsWkbTypes,
)

from .output_writer import OutputWriter
from .proximity_engine import ProximityEngine


FORM_CLASS, _ = uic.loadUiType(
    os.path.join(os.path.dirname(__file__), "proxivec_dialog_base.ui")
)


class DialogFeedback(QgsProcessingFeedback):
    def __init__(self, bridge):
        super().__init__()
        self.bridge = bridge

    def setProgress(self, progress):
        super().setProgress(progress)
        if self.bridge is not None:
            self.bridge.progressChanged.emit(int(progress))

    def pushInfo(self, info):
        super().pushInfo(info)
        if self.bridge is not None:
            self.bridge.messageChanged.emit(str(info))

    def reportError(self, error, fatalError=False):
        super().reportError(error, fatalError)
        if self.bridge is not None:
            self.bridge.messageChanged.emit(str(error))


class ProgressBridge(QObject):
    progressChanged = pyqtSignal(int)
    messageChanged = pyqtSignal(str)


class ProxiVecDialog(QDialog, FORM_CLASS):
    LOG_TAG = "ProxiVec"
    SETTINGS_KEY_TARGET_DIR = "ProxiVec/lastTargetDir"
    SETTINGS_KEY_OUTPUT_DIR = "ProxiVec/lastOutputDir"
    EXTENT_TARGET = "target"
    EXTENT_CANVAS = "canvas"
    EXTENT_LAYER = "layer"
    EXTENT_POLYGON = "polygon"

    def __init__(self, iface, parent=None):
        super().__init__(parent or iface.mainWindow())
        self.iface = iface
        self.setupUi(self)

        run_button = self.buttonBox.button(QDialogButtonBox.Ok)
        run_button.setText("Run")

        self.buttonBox.accepted.connect(self.run_analysis)
        self.buttonBox.rejected.connect(self.reject)

        self.targetLayerCombo.currentIndexChanged.connect(self.update_working_crs_info)
        self.extentModeCombo.currentIndexChanged.connect(self.update_extent_controls)
        self.extentLayerCombo.currentIndexChanged.connect(self.update_extent_controls)
        self.polygonExtentLayerCombo.currentIndexChanged.connect(self.update_extent_controls)
        self.extentUseSelectedCheck.toggled.connect(self.update_extent_controls)
        self.pixelSizeSpin.valueChanged.connect(self.update_working_crs_info)
        self.maxDistanceCheck.toggled.connect(self.maxDistanceSpin.setEnabled)
        self.refreshButton.clicked.connect(self.refresh_layers)
        self.outputBrowseButton.clicked.connect(self.choose_output_path)
        self.targetLayerBrowseButton.clicked.connect(self.choose_target_layer)

        self.progressGroupBox.setVisible(False)
        self.progressBar.setValue(0)
        self.progressLabel.setText("")
        self.progressBridge = ProgressBridge()
        self.progressBridge.progressChanged.connect(self.progressBar.setValue)
        self.progressBridge.messageChanged.connect(self.progressLabel.setText)
        browse_width = self.outputBrowseButton.sizeHint().width()
        self.outputBrowseButton.setFixedWidth(browse_width)
        self.targetLayerBrowseButton.setFixedWidth(browse_width)

        self.refresh_layers()
        self.maxDistanceSpin.setEnabled(self.maxDistanceCheck.isChecked())
        self.update_extent_controls()

    def refresh_layers(self):
        target_id = self.targetLayerCombo.currentData()
        extent_layer_id = self.extentLayerCombo.currentData()
        polygon_layer_id = self.polygonExtentLayerCombo.currentData()

        self.targetLayerCombo.clear()
        self.extentLayerCombo.clear()
        self.polygonExtentLayerCombo.clear()

        for layer in QgsProject.instance().mapLayers().values():
            if layer.type() == QgsMapLayerType.VectorLayer:
                self.targetLayerCombo.addItem(layer.name(), layer.id())

                geometry_type = QgsWkbTypes.geometryType(layer.wkbType())
                if geometry_type == QgsWkbTypes.PolygonGeometry:
                    self.polygonExtentLayerCombo.addItem(layer.name(), layer.id())

            self.extentLayerCombo.addItem(layer.name(), layer.id())

        self._restore_selection(self.targetLayerCombo, target_id)
        self._restore_selection(self.extentLayerCombo, extent_layer_id)
        self._restore_selection(self.polygonExtentLayerCombo, polygon_layer_id)
        self.update_working_crs_info()
        self.update_extent_controls()

    def update_working_crs_info(self):
        target_layer = self._current_layer(self.targetLayerCombo)

        run_button = self.buttonBox.button(QDialogButtonBox.Ok)
        run_button.setEnabled(target_layer is not None)

        if target_layer is None:
            self.crsInfoLabel.setText("Select a target layer to preview the working CRS.")
            return

        try:
            engine = ProximityEngine(
                target_layer=target_layer,
                pixel_size=max(self.pixelSizeSpin.value(), 1e-9),
                output_path=self.outputPathEdit.text().strip() or os.path.join(
                    os.path.expanduser("~"), "proxivec_proximity.tif"
                ),
                log_initial_state=False,
            )
            info_text = (
                f"Working CRS: {engine._crs_label(engine.working_crs)}\n"
                f"Reason: {engine.working_crs_reason}"
            )
            info_text += "\nDistance units: meters"
            if target_layer.crs().isGeographic():
                info_text += "\nGeographic target CRS will be reprojected to a projected working CRS."
            self.crsInfoLabel.setText(info_text)
        except Exception as exc:
            self.crsInfoLabel.setText(f"Failed to resolve working CRS: {exc}")

    def run_analysis(self):
        target_layer = self._current_layer(self.targetLayerCombo)

        if target_layer is None:
            QMessageBox.warning(self, "ProxiVec", "Target layer is required.")
            return

        output_path = self.outputPathEdit.text().strip()
        if not output_path:
            QMessageBox.warning(self, "ProxiVec", "Output raster path is required.")
            return

        output_dir = os.path.dirname(output_path)
        if output_dir and not os.path.isdir(output_dir):
            QMessageBox.warning(self, "ProxiVec", "Output folder was not found.")
            return

        run_button = self.buttonBox.button(QDialogButtonBox.Ok)
        run_button.setEnabled(False)
        self.progressGroupBox.setVisible(True)
        self.progressBar.setValue(0)
        self.progressLabel.setText("Starting...")

        feedback = DialogFeedback(self.progressBridge)
        try:
            analysis_extent, analysis_extent_crs = self._selected_extent()
            engine = ProximityEngine(
                target_layer=target_layer,
                target_expression=self.targetExpressionEdit.text(),
                target_selected_only=self.targetSelectedCheck.isChecked(),
                pixel_size=self.pixelSizeSpin.value(),
                output_path=output_path,
                analysis_extent=analysis_extent,
                analysis_extent_crs=analysis_extent_crs,
                max_distance=self.maxDistanceSpin.value()
                if self.maxDistanceCheck.isChecked()
                else None,
            )
            self.update_working_crs_info()

            result = engine.compute(feedback=feedback)
            feedback.setProgress(98)
            feedback.pushInfo("Loading output raster...")

            raster_layer = None
            if self.loadRasterCheckBox.isChecked():
                writer = OutputWriter()
                raster_layer = writer.load_raster(result.output_path, None)

            feedback.setProgress(100)
            feedback.pushInfo("Done.")

            summary = engine.build_summary(result)
            if raster_layer is not None:
                summary += f"\nLoaded layer: {raster_layer.name()}"
            QMessageBox.information(self, "ProxiVec", summary)
            self.accept()
        except ValueError as exc:
            QMessageBox.warning(self, "ProxiVec", str(exc))
        except Exception as exc:
            self._log(f"Error while running ProxiVec: {exc}", Qgis.Critical)
            QMessageBox.critical(
                self,
                "ProxiVec",
                f"An error occurred while running the analysis:\n{exc}",
            )
        finally:
            run_button.setEnabled(True)

    def choose_output_path(self):
        settings = QgsSettings()
        default_dir = settings.value(
            self.SETTINGS_KEY_OUTPUT_DIR,
            self.outputPathEdit.text().strip() or os.path.expanduser("~"),
            type=str,
        )
        if default_dir and os.path.isfile(default_dir):
            default_dir = os.path.dirname(default_dir)

        output_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save proximity raster",
            os.path.join(default_dir, "proxivec_proximity.tif"),
            "GeoTIFF (*.tif)",
        )
        if output_path:
            self.outputPathEdit.setText(output_path)
            settings.setValue(self.SETTINGS_KEY_OUTPUT_DIR, os.path.dirname(output_path))

    def choose_target_layer(self):
        settings = QgsSettings()
        default_dir = settings.value(
            self.SETTINGS_KEY_TARGET_DIR,
            os.path.expanduser("~"),
            type=str,
        )
        if default_dir and os.path.isfile(default_dir):
            default_dir = os.path.dirname(default_dir)

        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Open target vector layer",
            default_dir,
            "Vector data (*.gpkg *.shp *.geojson *.json *.kml *.sqlite *.tab *.gml *.dxf);;All files (*.*)",
        )
        if not file_path:
            return

        settings.setValue(self.SETTINGS_KEY_TARGET_DIR, os.path.dirname(file_path))
        layer_name = os.path.splitext(os.path.basename(file_path))[0]
        vector_layer = QgsVectorLayer(file_path, layer_name, "ogr")
        if not vector_layer.isValid():
            QMessageBox.warning(self, "ProxiVec", "Failed to open the selected vector layer.")
            return

        QgsProject.instance().addMapLayer(vector_layer)
        self.refresh_layers()
        layer_id = vector_layer.id()
        index = self.targetLayerCombo.findData(layer_id)
        if index >= 0:
            self.targetLayerCombo.setCurrentIndex(index)

    def _extent_mode(self):
        idx = self.extentModeCombo.currentIndex()
        data = self.extentModeCombo.itemData(idx, Qt.UserRole)
        if isinstance(data, str):
            data = data.strip().lower()

        if data in {self.EXTENT_TARGET, self.EXTENT_CANVAS, self.EXTENT_LAYER, self.EXTENT_POLYGON}:
            return data

        text = (self.extentModeCombo.currentText() or "").strip().lower()
        if "canvas" in text:
            return self.EXTENT_CANVAS
        if "polygon" in text:
            return self.EXTENT_POLYGON
        if "calculate" in text or "layer extent" in text:
            return self.EXTENT_LAYER
        return self.EXTENT_TARGET

    def update_extent_controls(self):
        mode = self._extent_mode()

        use_layer = mode == self.EXTENT_LAYER
        use_polygon = mode == self.EXTENT_POLYGON

        self.extentLayerCombo.setEnabled(use_layer)
        self.polygonExtentLayerCombo.setEnabled(use_polygon)
        self.extentLayerLabel.setEnabled(use_layer)
        self.polygonLayerLabel.setEnabled(use_polygon)

        self.extentUseSelectedCheck.setEnabled(use_layer or use_polygon)

        selected_only = self.extentUseSelectedCheck.isChecked()
        selected_hint = " (selected features only)" if selected_only else ""

        if mode == self.EXTENT_CANVAS:
            self.extentHintLabel.setText("Analysis extent will follow the current canvas extent.")
        elif mode == self.EXTENT_LAYER:
            layer = self._current_layer(self.extentLayerCombo)
            layer_name = layer.name() if layer else "None"
            self.extentHintLabel.setText(
                f"Analysis extent will be calculated from layer extent: {layer_name}{selected_hint}."
            )
        elif mode == self.EXTENT_POLYGON:
            layer = self._current_layer(self.polygonExtentLayerCombo)
            layer_name = layer.name() if layer else "None"
            self.extentHintLabel.setText(
                f"Analysis extent will use the bounding box of polygon layer: {layer_name}{selected_hint}."
            )
        else:
            self.extentHintLabel.setText(
                "Analysis extent will follow the target layer extent after reprojection."
            )

    def _selected_extent(self):
        mode = self._extent_mode()
        if mode == self.EXTENT_CANVAS:
            canvas = self.iface.mapCanvas()
            return canvas.extent(), canvas.mapSettings().destinationCrs()
        if mode == self.EXTENT_LAYER:
            layer = self._current_layer(self.extentLayerCombo)
            if layer is None:
                raise ValueError("Extent layer is required for the selected extent mode.")
            return self._extent_from_layer(layer)
        if mode == self.EXTENT_POLYGON:
            layer = self._current_layer(self.polygonExtentLayerCombo)
            if layer is None:
                raise ValueError("Polygon extent layer is required for the selected extent mode.")
            return self._extent_from_layer(layer)
        return None, None

    def _extent_from_layer(self, layer):
        if layer is None:
            return None, None

        if layer.type() == QgsMapLayerType.RasterLayer:
            return layer.extent(), layer.crs()

        if layer.type() != QgsMapLayerType.VectorLayer:
            return None, None

        selected_only = self.extentUseSelectedCheck.isChecked()
        if not selected_only:
            return layer.extent(), layer.crs()

        features = layer.selectedFeatures()
        extent = None
        for feature in features:
            geometry = feature.geometry()
            if not geometry or geometry.isEmpty():
                continue
            bbox = geometry.boundingBox()
            if extent is None:
                extent = bbox
            else:
                extent.combineExtentWith(bbox)

        if extent is None or extent.isEmpty():
            raise ValueError("Selected extent source layer has no valid geometry.")

        return extent, layer.crs()

    def _current_layer(self, combo_box):
        layer_id = combo_box.currentData()
        if not layer_id:
            return None
        return QgsProject.instance().mapLayer(layer_id)

    def _restore_selection(self, combo_box, layer_id):
        if not layer_id:
            return

        index = combo_box.findData(layer_id)
        if index >= 0:
            combo_box.setCurrentIndex(index)

    def _log(self, message, level=Qgis.Info):
        QgsMessageLog.logMessage(message, self.LOG_TAG, level)
