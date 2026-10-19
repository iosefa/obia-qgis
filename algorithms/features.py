from qgis.core import (
    QgsProcessingParameterBand,
    QgsProcessingParameterBoolean,
    QgsProcessingParameterEnum,
)

from .common import Algorithm


class ExtractFeatures(Algorithm):
    ID, TITLE = "extractfeatures", "Extract object features"
    HELP = (
        "<p>Measure raster values inside polygons; vectors are reprojected to the raster CRS. "
        "Choose band statistics, optional NDVI, shape, and texture. Shape in map units requires "
        "a projected raster CRS; choose pixel units for a geographic raster. Texture distances "
        "are pixels, and ranges are fitted per band over the image. NoData and polygon holes "
        "are excluded. Undefined measurements are NULL. Existing fields with the same name are replaced.</p>"
    )
    STATISTICS = [
        "mean",
        "std",
        "min",
        "max",
        "median",
        "iqr",
        "mad",
        "valid_count",
        "valid_fraction",
        "variance",
        "skewness",
        "kurtosis",
    ]

    def initAlgorithm(self, config=None):
        self.vector_input("OBJECTS", "Objects")
        self.raster_parameters()
        self.add(
            QgsProcessingParameterEnum(
                "STATISTICS",
                "Band statistics",
                options=self.STATISTICS,
                allowMultiple=True,
                defaultValue=[0, 1, 2, 3, 7],
                optional=True,
            )
        )
        self.add(
            QgsProcessingParameterBoolean(
                "PERCENTILES", "Include 10th and 90th percentiles", defaultValue=False
            ),
            True,
        )
        self.add(
            QgsProcessingParameterBoolean(
                "SHAPE", "Include shape measurements", defaultValue=False
            )
        )
        self.add(
            QgsProcessingParameterEnum(
                "SHAPE_UNITS",
                "Shape units",
                options=["Map units (projected CRS required)", "Pixels"],
                defaultValue=0,
            ),
            True,
        )
        self.add(
            QgsProcessingParameterBoolean(
                "TEXTURE", "Include GLCM texture for selected bands", defaultValue=False
            )
        )
        self.number(
            "TEXTURE_DISTANCE",
            "Texture distance (pixels)",
            1,
            1,
            integer=True,
            advanced=True,
        )
        self.number(
            "TEXTURE_LEVELS",
            "Texture gray levels",
            32,
            2,
            256,
            integer=True,
            advanced=True,
        )
        self.add(
            QgsProcessingParameterBand(
                "NIR",
                "NDVI near-infrared band (set both NDVI bands)",
                parentLayerParameterName="INPUT",
                optional=True,
            ),
            True,
        )
        self.add(
            QgsProcessingParameterBand(
                "RED", "NDVI red band", parentLayerParameterName="INPUT", optional=True
            ),
            True,
        )
        self.vector_output(label="Objects with features")

    def prepare_job(self, p, c, f, directory):
        payload = self.raster_payload(p, c)
        nir, red = self.parameterAsInt(p, "NIR", c), self.parameterAsInt(p, "RED", c)
        if bool(nir > 0) != bool(red > 0):
            raise ValueError("Choose both NDVI bands, or leave both empty.")
        payload.update(
            objects=self.stage_vector(p, "OBJECTS", c, f, directory),
            output=self.parameterAsOutputLayer(p, "OUTPUT", c),
            statistics=[
                self.STATISTICS[i] for i in self.parameterAsEnums(p, "STATISTICS", c)
            ],
            percentiles=self.parameterAsBool(p, "PERCENTILES", c),
            shape=self.parameterAsBool(p, "SHAPE", c),
            shape_units=["map", "pixel"][self.parameterAsEnum(p, "SHAPE_UNITS", c)],
            texture=self.parameterAsBool(p, "TEXTURE", c),
            texture_distance=self.parameterAsInt(p, "TEXTURE_DISTANCE", c),
            texture_levels=self.parameterAsInt(p, "TEXTURE_LEVELS", c),
            indices={"ndvi": [nir, red]} if nir > 0 else {},
        )
        return "features", payload, {"OUTPUT": "output"}
