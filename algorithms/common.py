"""Shared QGIS parameters and file staging for the isolated OBIA worker."""

import json
from pathlib import Path
import tempfile

from qgis.core import (
    QgsFeatureSink,
    QgsProcessing,
    QgsProcessingAlgorithm,
    QgsProcessingException,
    QgsProcessingParameterBand,
    QgsProcessingParameterDefinition,
    QgsProcessingParameterFeatureSource,
    QgsProcessingParameterNumber,
    QgsProcessingParameterRasterLayer,
    QgsProcessingParameterVectorDestination,
    QgsVectorFileWriter,
)

from ..runtime.client import EngineError, EngineCanceled, call_engine
from ..runtime.manager import engine_python

ROOT = Path(__file__).resolve().parents[1]


class Algorithm(QgsProcessingAlgorithm):
    ID = ""
    TITLE = ""
    GROUP = "Objects"
    HELP = ""

    def name(self):
        return self.ID

    def displayName(self):
        return self.TITLE

    def group(self):
        return self.GROUP

    def groupId(self):
        return self.GROUP.lower()

    def createInstance(self):
        return type(self)()

    def helpUrl(self):
        return (ROOT / "docs/index.html").as_uri() + "#" + self.ID

    def shortHelpString(self):
        return self.HELP + (
            "<p>Requires the private OBIA 0.2.0 engine. Install it once from "
            "Plugins → OBIA → Set up OBIA. Raster band selectors use QGIS band numbers "
            "(1 is the first band); OBIA feature names use zero-based positions (b0 is band 1). "
            "The full raster is read into memory. Start with a clipped study area.</p>"
        )

    def add(self, parameter, advanced=False):
        if advanced:
            parameter.setFlags(
                parameter.flags() | QgsProcessingParameterDefinition.FlagAdvanced
            )
        self.addParameter(parameter)

    def number(
        self,
        name,
        label,
        default,
        minimum=0,
        maximum=None,
        integer=False,
        advanced=False,
    ):
        options = dict(
            type=QgsProcessingParameterNumber.Integer
            if integer
            else QgsProcessingParameterNumber.Double,
            defaultValue=default,
            minValue=minimum,
        )
        if maximum is not None:
            options["maxValue"] = maximum
        self.add(QgsProcessingParameterNumber(name, label, **options), advanced)

    def raster_parameters(self):
        self.add(QgsProcessingParameterRasterLayer("INPUT", "Raster"))
        self.add(
            QgsProcessingParameterBand(
                "BANDS",
                "Bands (empty = all)",
                parentLayerParameterName="INPUT",
                optional=True,
                allowMultiple=True,
            )
        )
        self.add(
            QgsProcessingParameterRasterLayer(
                "MASK", "Inclusion mask (nonzero = include; same grid)", optional=True
            ),
            True,
        )

    def vector_input(self, name, label, labels=False, optional=False):
        self.add(
            QgsProcessingParameterFeatureSource(
                name,
                label,
                types=[QgsProcessing.TypeVectorPolygon, QgsProcessing.TypeVectorPoint]
                if labels
                else [QgsProcessing.TypeVectorPolygon],
                optional=optional,
            )
        )

    def vector_output(self, name="OUTPUT", label="Objects", optional=False):
        self.add(
            QgsProcessingParameterVectorDestination(
                name,
                label,
                type=QgsProcessing.TypeVectorPolygon,
                optional=optional,
                createByDefault=not optional,
            )
        )

    def raster_path(self, parameters, name, context, optional=False):
        layer = self.parameterAsRasterLayer(parameters, name, context)
        if layer is None and optional:
            return None
        if layer is None or not layer.isValid():
            raise QgsProcessingException("Select a valid raster layer.")
        if layer.providerType() != "gdal" or not Path(layer.source()).is_file():
            raise QgsProcessingException(
                "Export this raster to a local GeoTIFF before using OBIA. Web layers and subdataset URIs are not supported."
            )
        if not layer.crs().isValid():
            raise QgsProcessingException(
                "The raster needs a CRS saved in the source file."
            )
        return str(Path(layer.source()).absolute())

    def raster_payload(self, parameters, context):
        return {
            "raster": self.raster_path(parameters, "INPUT", context),
            "bands": self.parameterAsInts(parameters, "BANDS", context),
            "mask": self.raster_path(parameters, "MASK", context, optional=True),
        }

    def stage_vector(self, parameters, name, context, feedback, directory):
        source = self.parameterAsSource(parameters, name, context)
        if source is None or not source.sourceCrs().isValid():
            raise QgsProcessingException("Select a valid vector input with a CRS.")
        path = str(Path(directory) / (name.lower() + ".gpkg"))
        options = QgsVectorFileWriter.SaveVectorOptions()
        options.driverName = "GPKG"
        options.layerName = "input"
        options.fileEncoding = "UTF-8"
        writer = QgsVectorFileWriter.create(
            path,
            source.fields(),
            source.wkbType(),
            source.sourceCrs(),
            context.transformContext(),
            options,
        )
        try:
            if writer.hasError() != QgsVectorFileWriter.NoError:
                raise QgsProcessingException(writer.errorMessage())
            for feature in source.getFeatures():
                if feedback.isCanceled():
                    raise EngineCanceled("OBIA processing was canceled.")
                if not writer.addFeature(feature, QgsFeatureSink.FastInsert):
                    raise QgsProcessingException(writer.lastError())
        finally:
            del writer  # Flush SQLite before the worker opens this file on Windows.
        return path

    def check_outputs(self, parameters, context, payload):
        # Staging changes vector paths: also protect their original source files.
        inputs = set()
        for name in ("OBJECTS", "TRAINING", "POINTS", "TEST"):
            if self.parameterDefinition(name) is not None:
                layer = self.parameterAsVectorLayer(parameters, name, context)
                if layer is not None:
                    inputs.add(Path(layer.source().split("|")[0]).resolve())
        outputs = [
            Path(payload[key]).resolve()
            for key in ("output", "labels", "mixed", "report", "matrix")
            if payload.get(key)
        ]
        if inputs.intersection(outputs):
            raise QgsProcessingException(
                "Choose a new output file, separate from the input data."
            )

    def processAlgorithm(self, parameters, context, feedback):
        if engine_python() is None:
            raise QgsProcessingException(
                "Install the OBIA engine from Plugins → OBIA → Set up OBIA, then run this tool again."
            )
        try:
            with tempfile.TemporaryDirectory(prefix="obia-input-") as directory:
                operation, payload, outputs = self.prepare_job(
                    parameters, context, feedback, directory
                )
                self.check_outputs(parameters, context, payload)
                feedback.pushInfo("Running OBIA 0.2.0 in the private engine.")
                result = call_engine(operation, payload, feedback)
                feedback.pushInfo(json.dumps(result, ensure_ascii=False))
                return {
                    name: payload[key]
                    for name, key in outputs.items()
                    if payload.get(key)
                }
        except EngineCanceled:
            return {}
        except (EngineError, OSError, ValueError) as exc:
            raise QgsProcessingException(str(exc)) from exc
