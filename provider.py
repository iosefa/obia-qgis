from pathlib import Path

from qgis.PyQt.QtGui import QIcon
from qgis.core import QgsProcessingProvider

from .algorithms.segmentation import (
    SlicSegmentation,
    TiledSlicSegmentation,
    FelzenszwalbSegmentation,
    QuickshiftSegmentation,
    WatershedSegmentation,
)
from .algorithms.features import ExtractFeatures
from .algorithms.classification import LabelObjects, ClassifyObjects, ClassifyPixels
from .algorithms.dependency_check import CheckDependencies
from .algorithms.accuracy import ConfusionMatrix


class OBIAProvider(QgsProcessingProvider):
    def id(self):
        return "obia"

    def name(self):
        return "OBIA"

    def longName(self):
        return "OBIA — object-based raster analysis"

    def icon(self):
        return QIcon(str(Path(__file__).resolve().parent / "icons/icon.svg"))

    def loadAlgorithms(self):
        for cls in (
            SlicSegmentation,
            TiledSlicSegmentation,
            FelzenszwalbSegmentation,
            QuickshiftSegmentation,
            WatershedSegmentation,
            ExtractFeatures,
            LabelObjects,
            ClassifyObjects,
            ClassifyPixels,
            ConfusionMatrix,
            CheckDependencies,
        ):
            self.addAlgorithm(cls())

    def supportsNonFileBasedOutput(self):
        return False

    def supportedOutputVectorLayerExtensions(self):
        return ["gpkg"]

    def supportedOutputRasterLayerExtensions(self):
        return ["tif"]
