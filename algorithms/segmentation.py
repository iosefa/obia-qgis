from qgis.core import (
    QgsProcessingParameterBoolean,
    QgsProcessingParameterRasterDestination,
)

from .common import Algorithm


class Segmentation(Algorithm):
    GROUP = "Segmentation"
    METHOD = "slic"
    HELP = (
        "<p>Create object polygons and band mean, standard deviation, and valid-count fields. "
        "Optionally save matching segment IDs as a GeoTIFF; zero is NoData. Source masks are "
        "respected. Selected bands are normalized to [0, 1] for segmentation, with no RGB-to-Lab "
        "conversion. Statistics use the original pixel values.</p>"
    )

    def initAlgorithm(self, config=None):
        self.raster_parameters()
        if self.METHOD == "slic":
            self.number(
                "SEGMENTS", "Approximate number of objects", 1000, 1, integer=True
            )
            self.number("COMPACTNESS", "Compactness", 10, 0.000001)
            self.number("SIGMA", "Smoothing sigma (pixels)", 0, advanced=True)
            self.add(
                QgsProcessingParameterBoolean(
                    "SLIC_ZERO", "Use SLICO adaptive compactness", defaultValue=False
                ),
                True,
            )
        elif self.METHOD == "felzenszwalb":
            self.number("SCALE", "Scale (larger = larger objects)", 100, 0.000001)
            self.number("SIGMA", "Smoothing sigma (pixels)", 0.8)
            self.number("MIN_SIZE", "Minimum object size (pixels)", 50, 1, integer=True)
        elif self.METHOD == "quickshift":
            self.number("KERNEL_SIZE", "Kernel size", 3, 0.000001)
            self.number("MAX_DIST", "Maximum distance", 6, 0.000001)
            self.number("RATIO", "Color-to-space ratio", 0.5, 0, 1)
        elif self.METHOD == "watershed":
            self.number(
                "MARKERS", "Approximate number of basins", 1000, 1, integer=True
            )
            self.number("COMPACTNESS", "Compactness", 0)
        self.vector_output()
        self.add(
            QgsProcessingParameterRasterDestination(
                "LABELS", "Segment IDs", optional=True, createByDefault=False
            )
        )

    def prepare_job(self, p, c, feedback, directory):
        payload = self.raster_payload(p, c)
        if self.METHOD == "slic":
            options = dict(
                n_segments=self.parameterAsInt(p, "SEGMENTS", c),
                compactness=self.parameterAsDouble(p, "COMPACTNESS", c),
                sigma=self.parameterAsDouble(p, "SIGMA", c),
                convert2lab=False,
                slic_zero=self.parameterAsBool(p, "SLIC_ZERO", c),
            )
        elif self.METHOD == "felzenszwalb":
            options = dict(
                scale=self.parameterAsDouble(p, "SCALE", c),
                sigma=self.parameterAsDouble(p, "SIGMA", c),
                min_size=self.parameterAsInt(p, "MIN_SIZE", c),
            )
        elif self.METHOD == "quickshift":
            options = dict(
                kernel_size=self.parameterAsDouble(p, "KERNEL_SIZE", c),
                max_dist=self.parameterAsDouble(p, "MAX_DIST", c),
                ratio=self.parameterAsDouble(p, "RATIO", c),
                convert2lab=False,
            )
        else:
            options = dict(
                markers=self.parameterAsInt(p, "MARKERS", c),
                compactness=self.parameterAsDouble(p, "COMPACTNESS", c),
            )
        payload.update(
            method=self.METHOD,
            options=options,
            output=self.parameterAsOutputLayer(p, "OUTPUT", c),
            labels=self.parameterAsOutputLayer(p, "LABELS", c),
        )
        return "segment", payload, {"OUTPUT": "output", "LABELS": "labels"}


class SlicSegmentation(Segmentation):
    ID, TITLE, METHOD = "slic", "SLIC segmentation", "slic"


class FelzenszwalbSegmentation(Segmentation):
    ID, TITLE, METHOD = "felzenszwalb", "Felzenszwalb segmentation", "felzenszwalb"


class QuickshiftSegmentation(Segmentation):
    ID, TITLE, METHOD = "quickshift", "Quickshift segmentation", "quickshift"


class WatershedSegmentation(Segmentation):
    ID, TITLE, METHOD = "watershed", "Watershed segmentation", "watershed"
    HELP = (
        "<p>Select exactly one surface band. Watershed floods low values first; use a gradient raster to find image boundaries.</p>"
        + Segmentation.HELP
    )
