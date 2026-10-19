# Adapted from PyForestScan for QGIS.
# Copyright (C) 2026 Nicholas Rogers and Joseph Percival.
# GPL-2.0-or-later; this adaptation is distributed under GPL-3.0-only.
"""One QGIS application and isolated profile for the entire test process.

Qt supports one QApplication per process. Recreating it between test classes
also leaves QGIS GUI registries pointing to objects from the previous instance.
"""

import atexit
import gc
import tempfile


_application = None
_profile = None


def qgis_application():
    global _application, _profile
    if _application is None:
        from qgis.core import QgsApplication

        _profile = tempfile.TemporaryDirectory(prefix="obia-qgis-profile-")
        _application = QgsApplication([], False, _profile.name)
        _application.initQgis()
        atexit.register(_shutdown_qgis)
    return _application


def _shutdown_qgis():
    global _application, _profile
    if _application is not None:
        from qgis.core import QgsProject
        from qgis.PyQt import sip
        from qgis.PyQt.QtCore import QCoreApplication, QEvent

        # Destroy layers and deferred Qt objects while their providers still exist.
        QgsProject.instance().clear()
        gc.collect()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        _application.exitQgis()
        # Do not defer native QApplication destruction to Python finalization.
        sip.delete(_application)
        _application = None
    if _profile is not None:
        _profile.cleanup()
        _profile = None
