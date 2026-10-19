from html import escape
import json
from pathlib import Path

from qgis.core import (
    QgsProcessingException,
    QgsProcessingParameterFileDestination,
    QgsProcessingOutputBoolean,
)

from .common import Algorithm
from ..runtime import manager
from ..runtime.client import EngineError, EngineCanceled, call_engine


class CheckDependencies(Algorithm):
    ID, TITLE, GROUP = "checkdependencies", "Check OBIA dependencies", "Setup"
    HELP = "<p>Check the installed engine with real raster segmentation, feature extraction, vector labels, and classification operations. View the HTML report in Processing → Results Viewer.</p>"

    def initAlgorithm(self, config=None):
        self.add(
            QgsProcessingParameterFileDestination(
                "REPORT", "Dependency report", fileFilter="HTML files (*.html)"
            )
        )
        self.addOutput(QgsProcessingOutputBoolean("READY", "Engine ready"))

    def processAlgorithm(self, p, c, f):
        state = manager.status()
        ready = False
        if state["installed"]:
            try:
                state["selftest"] = call_engine("selftest", {}, f)
                ready = state["selftest"].get("ready") is True
            except EngineCanceled:
                return {}
            except EngineError as exc:
                state["error"] = str(exc)
        else:
            state["instructions"] = (
                "Open Plugins → OBIA → Set up OBIA and click Install engine."
            )
        path = self.parameterAsFileOutput(p, "REPORT", c)
        text = json.dumps(state, indent=2, ensure_ascii=False)
        f.pushInfo(("OK\n" if ready else "Engine unavailable\n") + text)
        try:
            Path(path).write_text(
                "<!doctype html><html><meta charset='utf-8'><title>OBIA dependencies</title><body><h1>"
                + ("OBIA engine ready" if ready else "OBIA engine unavailable")
                + "</h1><pre>"
                + escape(text)
                + "</pre></body></html>",
                encoding="utf-8",
            )
        except OSError as exc:
            raise QgsProcessingException(str(exc)) from exc
        return {"REPORT": path, "READY": ready}
