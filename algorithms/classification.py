from qgis.core import (
    QgsProcessingParameterEnum,
    QgsProcessingParameterField,
    QgsProcessingParameterFileDestination,
    QgsProcessingParameterRasterDestination,
)

from .common import Algorithm


class LabelObjects(Algorithm):
    ID, TITLE = "labelobjects", "Label objects from points"
    HELP = (
        "<p>Assign point classes to intersecting polygons, reprojecting points to the objects' CRS. "
        "The output contains only objects with one agreed class, stored in feature_class. "
        "Objects with conflicting labels are excluded and can be saved separately for review. "
        "Unlabelled objects are excluded. A point on a boundary may label both adjacent objects. "
        "Previous feature_class values are cleared before assigning labels.</p>"
    )

    def initAlgorithm(self, config=None):
        self.vector_input("OBJECTS", "Objects with features")
        self.vector_input("POINTS", "Labelled points", points=True)
        self.add(
            QgsProcessingParameterField(
                "CLASS_FIELD",
                "Point class field",
                parentLayerParameterName="POINTS",
                defaultValue="class",
            )
        )
        self.vector_output(label="Labelled training objects")
        self.vector_output("MIXED", "Objects with conflicting labels", optional=True)

    def prepare_job(self, p, c, f, directory):
        return (
            "label",
            dict(
                objects=self.stage_vector(p, "OBJECTS", c, f, directory),
                points=self.stage_vector(p, "POINTS", c, f, directory),
                label_field=self.parameterAsString(p, "CLASS_FIELD", c),
                output=self.parameterAsOutputLayer(p, "OUTPUT", c),
                mixed=self.parameterAsOutputLayer(p, "MIXED", c),
            ),
            {"OUTPUT": "output", "MIXED": "mixed"},
        )


class Classifier(Algorithm):
    GROUP = "Classification"
    HELP = (
        "<p>Train Random Forest, Extra Trees, or XGBoost and predict classes. Supply an optional "
        "labelled test layer to train on all training samples and evaluate only against that layer. "
        "The test class field defaults to the training class field; test classes must occur in training. "
        "Holdout settings are ignored when test data is supplied. Without test data, a 20% stratified "
        "random holdout is reserved by default; set the fraction to 0 to fit all samples without "
        "an accuracy estimate. Advanced parameters support grouped or spatial holdouts and a "
        "buffer in projected CRS units. Every class must occur in training. The fitted model "
        "is not automatically refitted on the holdout. Reports describe the test data or holdout only. "
        "Use spatial/grouped validation to assess transfer to new areas.</p>"
    )

    def createCustomParametersWidget(self, parent=None):
        from .classification_dialog import ClassificationDialog

        return ClassificationDialog(self, parent=parent)

    def test_parameters(self, points=False):
        self.vector_input(
            "TEST",
            "Labelled test points" if points else "Labelled test objects",
            points=points,
            optional=True,
        )
        self.add(
            QgsProcessingParameterField(
                "TEST_CLASS_FIELD",
                "Test class field (empty = training class field)",
                parentLayerParameterName="TEST",
                optional=True,
            )
        )

    def classifier_parameters(self, training):
        self.add(
            QgsProcessingParameterEnum(
                "METHOD",
                "Classifier",
                options=["Random Forest", "Extra Trees", "XGBoost"],
                defaultValue=0,
            )
        )
        self.number("TREES", "Number of trees", 200, 1, integer=True)
        self.number(
            "TEST_FRACTION",
            "Holdout fraction without test data (0 = train on all)",
            0.2,
            0,
            0.9,
        )
        self.number(
            "MAX_DEPTH",
            "Maximum tree depth (0 = forest unlimited / XGBoost 6)",
            0,
            integer=True,
            advanced=True,
        )
        self.number("SEED", "Random seed", 42, integer=True, advanced=True)
        self.add(
            QgsProcessingParameterEnum(
                "VALIDATION",
                "Holdout design",
                options=["Random stratified", "Grouped", "Spatial blocks"],
                defaultValue=0,
            ),
            True,
        )
        self.add(
            QgsProcessingParameterField(
                "GROUP_FIELD",
                "Group field (grouped holdout only)",
                parentLayerParameterName=training,
                optional=True,
            ),
            True,
        )
        self.number(
            "BLOCK_SIZE",
            "Spatial block size (projected CRS units)",
            500,
            0.000001,
            advanced=True,
        )
        self.number(
            "BUFFER", "Holdout buffer (projected CRS units; 0 = none)", 0, advanced=True
        )

    def classifier_payload(self, p, c, f, directory):
        test = None
        if p.get("TEST"):
            test = self.stage_vector(p, "TEST", c, f, directory)
        method = ["random", "grouped", "spatial"][
            self.parameterAsEnum(p, "VALIDATION", c)
        ]
        group = self.parameterAsString(p, "GROUP_FIELD", c)
        if not test and method == "grouped" and not group:
            raise ValueError("Choose a group field for grouped validation.")
        return dict(
            method=["rf", "extra_trees", "xgboost"][
                self.parameterAsEnum(p, "METHOD", c)
            ],
            trees=self.parameterAsInt(p, "TREES", c),
            max_depth=self.parameterAsInt(p, "MAX_DEPTH", c),
            test=test,
            test_label_field=self.parameterAsString(p, "TEST_CLASS_FIELD", c),
            test_fraction=None
            if test
            else self.parameterAsDouble(p, "TEST_FRACTION", c),
            seed=self.parameterAsInt(p, "SEED", c),
            validation="supplied test data" if test else method,
            group_field=group if method == "grouped" and not test else None,
            block_size=self.parameterAsDouble(p, "BLOCK_SIZE", c)
            if method == "spatial" and not test
            else None,
            buffer=0 if test else self.parameterAsDouble(p, "BUFFER", c),
            report=self.parameterAsFileOutput(p, "REPORT", c),
        )

    def report_parameter(self):
        self.add(
            QgsProcessingParameterFileDestination(
                "REPORT", "Classification report", fileFilter="HTML files (*.html)"
            )
        )


class ClassifyObjects(Classifier):
    ID, TITLE = "classifyobjects", "Classify objects"
    HELP = (
        "<p>Select numeric predictor fields present in the objects, training, and optional test layers. "
        "Training and test objects must be distinct. Exclude class labels, IDs, "
        "grouping fields, and previous predictions. Output adds predicted_class and prediction_margin "
        "to all objects; margin is the gap between the two highest class probabilities.</p>"
    ) + Classifier.HELP

    def initAlgorithm(self, config=None):
        self.vector_input("OBJECTS", "Objects to classify")
        self.vector_input("TRAINING", "Labelled training objects")
        self.add(
            QgsProcessingParameterField(
                "CLASS_FIELD",
                "Training class field",
                parentLayerParameterName="TRAINING",
                defaultValue="feature_class",
            )
        )
        self.add(
            QgsProcessingParameterField(
                "FEATURES",
                "Predictor fields",
                parentLayerParameterName="OBJECTS",
                type=QgsProcessingParameterField.Numeric,
                allowMultiple=True,
            )
        )
        self.test_parameters()
        self.classifier_parameters("TRAINING")
        self.vector_output(label="Classified objects")
        self.report_parameter()

    def prepare_job(self, p, c, f, directory):
        payload = self.classifier_payload(p, c, f, directory)
        payload.update(
            objects=self.stage_vector(p, "OBJECTS", c, f, directory),
            training=self.stage_vector(p, "TRAINING", c, f, directory),
            label_field=self.parameterAsString(p, "CLASS_FIELD", c),
            features=self.parameterAsStrings(p, "FEATURES", c),
            output=self.parameterAsOutputLayer(p, "OUTPUT", c),
        )
        return "classify_objects", payload, {"OUTPUT": "output", "REPORT": "report"}


class ClassifyPixels(Classifier):
    ID, TITLE = "classifypixels", "Classify pixels"
    HELP = (
        "<p>Train from raster pixels containing labelled points, then classify every valid pixel. "
        "Points are reprojected to the raster CRS. Outside/NoData points and conflicting labels "
        "in the same pixel stop processing. Matching duplicates count once. Optional test points "
        "are sampled from the same raster and must select different pixels from the training points. "
        "The output preserves "
        "the source grid with NoData 0 and class codes 1..K. The HTML report and GeoTIFF class_mapping "
        "tag link those codes to original labels.</p>"
    ) + Classifier.HELP

    def initAlgorithm(self, config=None):
        self.raster_parameters()
        self.vector_input("POINTS", "Labelled points", points=True)
        self.add(
            QgsProcessingParameterField(
                "CLASS_FIELD",
                "Point class field",
                parentLayerParameterName="POINTS",
                defaultValue="class",
            )
        )
        self.test_parameters(points=True)
        self.classifier_parameters("POINTS")
        self.add(QgsProcessingParameterRasterDestination("OUTPUT", "Classified pixels"))
        self.report_parameter()

    def prepare_job(self, p, c, f, directory):
        payload = self.classifier_payload(p, c, f, directory)
        payload.update(self.raster_payload(p, c))
        payload.update(
            points=self.stage_vector(p, "POINTS", c, f, directory),
            label_field=self.parameterAsString(p, "CLASS_FIELD", c),
            output=self.parameterAsOutputLayer(p, "OUTPUT", c),
        )
        return "classify_pixels", payload, {"OUTPUT": "output", "REPORT": "report"}
