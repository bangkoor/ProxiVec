import os

from qgis.core import QgsMessageLog, QgsProject, QgsRasterLayer, Qgis


class OutputWriter:
    LOG_TAG = "ProxiVec"

    def load_raster(self, raster_path, layer_name=None):
        if not raster_path or not os.path.exists(raster_path):
            raise ValueError("Output raster file was not found.")

        layer_label = layer_name or os.path.splitext(os.path.basename(raster_path))[0]
        raster_layer = QgsRasterLayer(raster_path, layer_label)
        if not raster_layer.isValid():
            raise ValueError("Failed to load output raster into QGIS.")

        QgsProject.instance().addMapLayer(raster_layer)
        self._log(f"Output raster loaded into the project: {raster_layer.name()}")
        return raster_layer

    def _log(self, message, level=Qgis.Info):
        QgsMessageLog.logMessage(message, self.LOG_TAG, level)
