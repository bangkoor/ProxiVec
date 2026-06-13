import os

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QIcon
from PyQt5.QtWidgets import QAction

from .proxivec_dialog import ProxiVecDialog


class ProxiVecPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.plugin_dir = os.path.dirname(__file__)
        self.action = None
        self.dialog = None
        self.menu_name = "&ProxiVec"

    def initGui(self):
        icon_path = os.path.join(self.plugin_dir, "icon.png")
        self.action = QAction(QIcon(icon_path), "Proximity Analysis", self.iface.mainWindow())
        self.action.triggered.connect(self.run)

        self.iface.addToolBarIcon(self.action)
        self.iface.addPluginToVectorMenu(self.menu_name, self.action)

    def unload(self):
        if not self.action:
            return

        if self.dialog is not None:
            self.dialog.close()
            self.dialog = None

        self.iface.removePluginVectorMenu(self.menu_name, self.action)
        self.iface.removeToolBarIcon(self.action)
        self.action = None

    def run(self):
        if self.dialog is None:
            self.dialog = ProxiVecDialog(self.iface)
            self.dialog.setWindowModality(Qt.NonModal)
            self.dialog.setAttribute(Qt.WA_DeleteOnClose, False)

        if self.dialog.isMinimized():
            self.dialog.showNormal()
        else:
            self.dialog.show()
        self.dialog.raise_()
        self.dialog.activateWindow()
