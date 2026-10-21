"""Accuracy of an existing classified raster against labelled test geometries."""

from qgis.core import (
    QgsProcessingParameterField,
    QgsProcessingParameterFileDestination,
    QgsProcessingParameterRasterLayer,
)

from .common import Algorithm


class ConfusionMatrix(Algorithm):
    ID, TITLE = "confusionmatrix", "Confusion matrix from raster"
    GROUP = "Classification"
    HELP = (
        "<p>Compare a single-band classified raster with labelled test points or polygons. "
        "Labels are reprojected to the raster CRS. Every pixel touched by a polygon is sampled; "
        "holes are respected and polygons are clipped to the raster extent. OBIA GeoTIFF class mappings are "
        "used automatically; for other rasters, the test field must contain numeric "
        "raster class codes. Outside points, polygons with no intersecting pixels, NoData pixels, "
        "and conflicting labels in one pixel stop processing. Matching labels count once per pixel.</p>"
        "<p>The UTF-8 text file is tab separated: rows are observed test classes, "
        "columns are predicted raster classes, and cells are sample counts. "
        "This tool evaluates an existing raster without fitting a model.</p>"
    )

    def shortHelpString(self):
        return self.HELP + (
            "<p>Requires the private OBIA 0.2.0 engine. Install it once from "
            "Plugins → OBIA → Set up OBIA.</p>"
        )

    def initAlgorithm(self, config=None):
        self.add(QgsProcessingParameterRasterLayer("INPUT", "Classified raster"))
        self.vector_input("POINTS", "Labelled test points or polygons", labels=True)
        self.add(
            QgsProcessingParameterField(
                "CLASS_FIELD",
                "Test class field",
                parentLayerParameterName="POINTS",
                defaultValue="class",
            )
        )
        self.add(
            QgsProcessingParameterFileDestination(
                "OUTPUT",
                "Confusion matrix (tab-separated text)",
                fileFilter="Text files (*.txt)",
            )
        )

    def prepare_job(self, p, c, f, directory):
        return (
            "confusion_matrix",
            dict(
                raster=self.raster_path(p, "INPUT", c),
                points=self.stage_vector(p, "POINTS", c, f, directory),
                label_field=self.parameterAsString(p, "CLASS_FIELD", c),
                matrix=self.parameterAsFileOutput(p, "OUTPUT", c),
            ),
            {"OUTPUT": "matrix"},
        )
