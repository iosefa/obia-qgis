"""Run against actual Qt 5/6 QGIS, with the private engine installed."""

import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(os.environ.get("OBIA_PLUGIN_PATH", Path(__file__).resolve().parents[1]))


@unittest.skipUnless(os.environ.get("OBIA_TEST_QGIS") == "1", "Requires a QGIS runtime")
class QgisIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from qgis_test_support import qgis_application
        from qgis.core import QgsApplication

        cls.app = qgis_application()
        spec = importlib.util.spec_from_file_location(
            "obia_qgis", ROOT / "__init__.py", submodule_search_locations=[str(ROOT)]
        )
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        from obia_qgis.obia_plugin import OBIAPlugin

        cls.plugin = OBIAPlugin(None)
        cls.plugin.initProcessing()
        cls.registry = QgsApplication.processingRegistry()

    @classmethod
    def tearDownClass(cls):
        cls.plugin.unload()

    def setUp(self):
        from qgis.core import (
            QgsProcessingContext,
            QgsProcessingFeedback,
            QgsRasterLayer,
            QgsProject,
        )
        from osgeo import gdal, osr
        import numpy as np

        self.directory = tempfile.TemporaryDirectory(prefix="obia qgis ü ")
        self.d = Path(self.directory.name)
        self.context = QgsProcessingContext()
        self.context.setProject(QgsProject.instance())
        self.feedback = QgsProcessingFeedback()
        path = self.d / "image.tif"
        ds = gdal.GetDriverByName("GTiff").Create(
            str(path), 32, 32, 2, gdal.GDT_Float32
        )
        ds.SetGeoTransform((100, 1, 0, 200, 0, -1))
        srs = osr.SpatialReference()
        srs.ImportFromEPSG(32605)
        ds.SetProjection(srs.ExportToWkt())
        yy, xx = np.mgrid[:32, :32]
        ds.GetRasterBand(1).WriteArray(xx.astype(float) + (xx >= 16) * 70 + yy * 0.01)
        ds.GetRasterBand(2).WriteArray(xx.astype(float) * 3 + 10)
        ds = None
        self.raster = QgsRasterLayer(str(path), "Test raster")
        self.assertTrue(self.raster.isValid())

    def tearDown(self):
        self.context = None
        self.raster = None
        self.directory.cleanup()

    def run_algorithm(self, name, parameters):
        algorithm = self.registry.algorithmById("obia:" + name)
        self.assertIsNotNone(algorithm)
        result, ok = algorithm.run(
            parameters, self.context, self.feedback, catchExceptions=False
        )
        self.assertTrue(ok)
        return result

    def segment(self):
        from qgis.core import QgsVectorLayer

        result = self.run_algorithm(
            "slic",
            dict(
                INPUT=self.raster,
                SEGMENTS=16,
                COMPACTNESS=1,
                OUTPUT=str(self.d / "objects.gpkg"),
                LABELS=str(self.d / "ids.tif"),
            ),
        )
        layer = QgsVectorLayer(result["OUTPUT"], "Objects", "ogr")
        self.assertTrue(layer.isValid())
        return layer

    def points(self, objects):
        from qgis.core import QgsVectorLayer, QgsFeature

        layer = QgsVectorLayer(
            "Point?crs=EPSG:32605&field=cover:string", "Labels", "memory"
        )
        for obj in objects.getFeatures():
            point = obj.geometry().pointOnSurface()
            f = QgsFeature(layer.fields())
            f.setGeometry(point)
            f.setAttributes(["forest" if point.asPoint().x() < 116 else "water"])
            self.assertTrue(layer.dataProvider().addFeatures([f])[0])
        return layer

    def test_provider_and_setup_do_not_import_obia(self):
        self.assertEqual(len(self.plugin.provider.algorithms()), 9)
        self.assertNotIn("obia", sys.modules)
        self.assertNotIn("rasterio", sys.modules)
        from obia_qgis.setup_dialog import SetupDialog

        dialog = SetupDialog()
        self.assertEqual(dialog.windowTitle(), "OBIA Setup")
        self.assertTrue(dialog.install_button.isEnabled())
        dialog.close()

    def test_all_segmentation_dialogs_and_band_selection(self):
        from qgis.core import QgsVectorLayer, QgsRasterLayer

        for method in ("slic", "felzenszwalb", "quickshift", "watershed"):
            with self.subTest(method=method):
                result = self.run_algorithm(
                    method,
                    dict(
                        INPUT=self.raster,
                        BANDS=[2],
                        OUTPUT=str(self.d / (method + ".gpkg")),
                        LABELS=str(self.d / (method + ".tif")),
                    ),
                )
                objects = QgsVectorLayer(result["OUTPUT"], "Objects", "ogr")
                labels = QgsRasterLayer(result["LABELS"], "IDs")
                self.assertTrue(objects.isValid())
                self.assertTrue(labels.isValid())
                self.assertIn("b1_mean", objects.fields().names())
                self.assertNotIn("b0_mean", objects.fields().names())

    def test_complete_object_and_pixel_workflow(self):
        from qgis.core import QgsVectorLayer, QgsRasterLayer

        objects = self.segment()
        features = self.run_algorithm(
            "extractfeatures",
            dict(
                OBJECTS=objects,
                INPUT=self.raster,
                SHAPE=True,
                TEXTURE=True,
                NIR=2,
                RED=1,
                OUTPUT=str(self.d / "features.gpkg"),
            ),
        )
        objects = QgsVectorLayer(features["OUTPUT"], "Features", "ogr")
        points = self.points(objects)
        labelled = self.run_algorithm(
            "labelobjects",
            dict(
                OBJECTS=objects,
                POINTS=points,
                CLASS_FIELD="cover",
                OUTPUT=str(self.d / "training.gpkg"),
                MIXED=str(self.d / "mixed.gpkg"),
            ),
        )
        training = QgsVectorLayer(labelled["OUTPUT"], "Training", "ogr")
        result = self.run_algorithm(
            "classifyobjects",
            dict(
                OBJECTS=objects,
                TRAINING=training,
                CLASS_FIELD="feature_class",
                FEATURES=["b0_mean", "b1_mean"],
                TREES=10,
                OUTPUT=str(self.d / "classes.gpkg"),
                REPORT=str(self.d / "objects.html"),
            ),
        )
        classified = QgsVectorLayer(result["OUTPUT"], "Classes", "ogr")
        self.assertIn("predicted_class", classified.fields().names())
        self.assertEqual(classified.featureCount(), objects.featureCount())
        result = self.run_algorithm(
            "classifypixels",
            dict(
                INPUT=self.raster,
                POINTS=points,
                CLASS_FIELD="cover",
                TREES=10,
                TEST_FRACTION=0,
                OUTPUT=str(self.d / "pixels.tif"),
                REPORT=str(self.d / "pixels.html"),
            ),
        )
        self.assertTrue(QgsRasterLayer(result["OUTPUT"], "Pixels").isValid())
        self.assertIn("forest", Path(result["REPORT"]).read_text())

    def test_selected_memory_features_and_edits_are_staged(self):
        from qgis.core import (
            QgsProcessingFeatureSourceDefinition,
            QgsVectorLayer,
            QgsProject,
        )

        objects = self.segment()
        points = self.points(objects)
        project = QgsProject.instance()
        project.addMapLayer(points)
        first = next(points.getFeatures())
        points.selectByIds([first.id()])
        points.startEditing()
        points.changeAttributeValue(first.id(), 0, "edited class")
        try:
            result = self.run_algorithm(
                "labelobjects",
                dict(
                    OBJECTS=objects,
                    POINTS=QgsProcessingFeatureSourceDefinition(
                        points.id(), selectedFeaturesOnly=True
                    ),
                    CLASS_FIELD="cover",
                    OUTPUT=str(self.d / "selected.gpkg"),
                ),
            )
            labelled = QgsVectorLayer(result["OUTPUT"], "Selected", "ogr")
            self.assertEqual(labelled.featureCount(), 1)
            self.assertEqual(
                next(labelled.getFeatures())["feature_class"], "edited class"
            )
        finally:
            project.removeMapLayer(points.id())

    def test_input_geopackage_cannot_be_replaced(self):
        from qgis.core import QgsProcessingException

        objects = self.segment()
        before = Path(objects.source()).read_bytes()
        with self.assertRaisesRegex(QgsProcessingException, "separate"):
            self.run_algorithm(
                "extractfeatures",
                dict(OBJECTS=objects, INPUT=self.raster, OUTPUT=objects.source()),
            )
        self.assertEqual(Path(objects.source()).read_bytes(), before)

    def test_dependency_report_runs_scientific_selftest(self):
        result = self.run_algorithm(
            "checkdependencies", {"REPORT": str(self.d / "dependencies.html")}
        )
        self.assertTrue(result["READY"])
        self.assertIn("0.2.0", Path(result["REPORT"]).read_text())


if __name__ == "__main__":
    unittest.main()
