"""Scientific integration tests run with the installed engine's Python."""

import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(os.environ.get("OBIA_PLUGIN_PATH", Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(ROOT))
from runtime.client import EngineError, call_with_python  # noqa: E402


class WorkerProtocolTests(unittest.TestCase):
    def test_unknown_operation_is_an_actionable_error(self):
        from runtime.manager import engine_python

        # QGIS.app's embedded executable is not a standalone Python installation.
        python = engine_python() or sys.executable
        with self.assertRaisesRegex(EngineError, "Unknown OBIA operation"):
            call_with_python(python, "not-an-operation", {})

    def test_bundled_release_hashes_are_unchanged(self):
        source = json.loads((ROOT / "vendor/obia/SOURCE.json").read_text())
        self.assertEqual(source["version"], "0.2.0")
        self.assertEqual(source["tag"], "v0.2.0")
        for filename, digest in source["files"].items():
            with self.subTest(filename=filename):
                self.assertEqual(
                    hashlib.sha256(
                        (ROOT / "vendor/obia" / filename).read_bytes()
                    ).hexdigest(),
                    digest,
                )


@unittest.skipUnless(
    os.environ.get("OBIA_TEST_ENGINE") == "1", "Run with the private engine interpreter"
)
class ScientificTests(unittest.TestCase):
    def setUp(self):
        from runtime.worker import configure_runtime

        configure_runtime()
        import numpy as np
        import geopandas as gpd
        import rasterio
        from rasterio.transform import from_origin
        from runtime import jobs

        self.jobs, self.np, self.gpd, self.rasterio = jobs, np, gpd, rasterio
        self.directory = tempfile.TemporaryDirectory(prefix="obia science ü ")
        self.d = Path(self.directory.name)
        self.raster = self.d / "input imagery.tif"
        yy, xx = np.mgrid[:32, :32]
        self.values = (xx + (xx >= 16) * 80 + yy * 0.03).astype("float32")
        self.transform = from_origin(100, 200, 1, 1)
        with rasterio.open(
            self.raster,
            "w",
            driver="GTiff",
            width=32,
            height=32,
            count=2,
            dtype="float32",
            crs="EPSG:32605",
            transform=self.transform,
            nodata=-9999,
        ) as dst:
            dst.write(self.values, 1)
            dst.write(self.values * 2 + 10, 2)
        self.objects = self.d / "objects.gpkg"
        jobs.segment_raster(
            dict(
                raster=str(self.raster),
                output=str(self.objects),
                labels=str(self.d / "ids.tif"),
                options=dict(n_segments=16, compactness=1, convert2lab=False),
            )
        )

    def tearDown(self):
        self.directory.cleanup()

    def points(self, path=None):
        objects = self.gpd.read_file(self.objects)
        geom = objects.representative_point()
        points = self.gpd.GeoDataFrame(
            {"cover": ["forest" if p.x < 116 else "water" for p in geom]},
            geometry=geom,
            crs=objects.crs,
        )
        output = path or self.d / "points.gpkg"
        points.to_file(output, index=False)
        return output

    def test_selftest_uses_real_scientific_operations(self):
        result = call_with_python(sys.executable, "selftest", {}, timeout=120)
        self.assertTrue(result["ready"])
        self.assertEqual(result["obia"], "0.2.0")

    def test_segmentation_labels_and_geometry_match(self):
        from rasterio.features import rasterize

        objects = self.gpd.read_file(self.objects)
        with self.rasterio.open(self.d / "ids.tif") as src:
            actual = src.read(1)
            expected = rasterize(
                zip(objects.geometry, objects.segment_id),
                out_shape=actual.shape,
                transform=src.transform,
            )
            self.np.testing.assert_array_equal(actual, expected)
            self.assertEqual(src.crs.to_epsg(), 32605)
            self.assertEqual(src.nodata, 0)
        self.assertTrue(objects.segment_id.is_unique)

    def test_segmentation_methods_and_one_based_band_conversion(self):
        for method, options in (
            ("felzenszwalb", dict(scale=50, min_size=10)),
            ("quickshift", dict(kernel_size=2, max_dist=5, convert2lab=False)),
            ("watershed", dict(markers=16)),
        ):
            with self.subTest(method=method):
                output = self.d / (method + ".gpkg")
                self.jobs.segment_raster(
                    dict(
                        raster=str(self.raster),
                        bands=[2],
                        method=method,
                        options=options,
                        output=str(output),
                    )
                )
                objects = self.gpd.read_file(output)
                self.assertGreater(len(objects), 0)
                self.assertIn("b1_mean", objects)
                self.assertNotIn("b0_mean", objects)

    def test_features_ndvi_shape_and_texture(self):
        output = self.d / "features.gpkg"
        self.jobs.extract_features(
            dict(
                raster=str(self.raster),
                objects=str(self.objects),
                output=str(output),
                bands=[2],
                shape=True,
                texture=True,
                indices={"ndvi": [2, 1]},
                percentiles=True,
            )
        )
        objects = self.gpd.read_file(output)
        self.assertIn("shape_area", objects)
        self.assertTrue(any("contrast" in c for c in objects.columns))
        self.assertTrue(any("index_ndvi_b1_b0" in c for c in objects.columns))
        self.assertAlmostEqual(objects.shape_area.sum(), 1024)

    def test_labels_conflicts_and_no_intersections(self):
        from shapely.geometry import Point

        points_path = self.points()
        points = self.gpd.read_file(points_path)
        first = points.iloc[[0]].copy()
        first["cover"] = "conflict"
        import pandas as pd

        points = pd.concat([points, first], ignore_index=True)
        points.to_file(points_path, index=False)
        result = self.jobs.label_objects(
            dict(
                objects=str(self.objects),
                points=str(points_path),
                label_field="cover",
                output=str(self.d / "train.gpkg"),
                mixed=str(self.d / "mixed.gpkg"),
            )
        )
        self.assertEqual(result["conflicting"], 1)
        self.assertEqual(result["labelled"], len(points) - 2)
        points = self.gpd.GeoDataFrame(
            {"cover": ["outside"]}, geometry=[Point(999, 999)], crs=points.crs
        )
        points.to_file(self.d / "outside.gpkg", index=False)
        result = self.jobs.label_objects(
            dict(
                objects=str(self.objects),
                points=str(self.d / "outside.gpkg"),
                label_field="cover",
                output=str(self.d / "empty.gpkg"),
            )
        )
        self.assertEqual(result["labelled"], 0)

    def training(self):
        path = self.d / "training.gpkg"
        self.jobs.label_objects(
            dict(
                objects=str(self.objects),
                points=str(self.points()),
                label_field="cover",
                output=str(path),
            )
        )
        return path

    def test_object_classifiers_and_holdout_reports(self):
        training = self.training()
        for method in ("rf", "extra_trees", "xgboost"):
            with self.subTest(method=method):
                output = self.d / (method + ".gpkg")
                report = self.d / (method + ".html")
                self.jobs.classify_objects(
                    dict(
                        objects=str(self.objects),
                        training=str(training),
                        features=["b0_mean", "b1_mean"],
                        method=method,
                        trees=8,
                        test_fraction=0.25,
                        output=str(output),
                        report=str(report),
                    )
                )
                data = self.gpd.read_file(output)
                self.assertFalse(data.predicted_class.isna().any())
                self.assertIn("precision", report.read_text())
                self.assertIn("holdout", report.read_text())

    def test_pixel_class_codes_georeferencing_and_report(self):
        output, report = self.d / "classes.tif", self.d / "classes.html"
        result = self.jobs.classify_pixels(
            dict(
                raster=str(self.raster),
                points=str(self.points()),
                label_field="cover",
                trees=10,
                test_fraction=0,
                output=str(output),
                report=str(report),
            )
        )
        with self.rasterio.open(output) as src:
            self.assertEqual(src.transform, self.transform)
            self.assertEqual(src.crs.to_epsg(), 32605)
            self.assertEqual(src.nodata, 0)
            self.assertEqual(
                json.loads(src.tags()["class_mapping"]), result["class_mapping"]
            )
            self.assertEqual(set(self.np.unique(src.read(1))), {1, 2})
        self.assertIn("No held-out accuracy", report.read_text())

    def test_mask_misalignment_and_band_errors_preserve_output(self):
        output = self.d / "preserved.gpkg"
        output.write_bytes(b"existing output")
        for selected in ([0], [3], [1, 1]):
            with self.assertRaises(ValueError):
                self.jobs.segment_raster(
                    dict(raster=str(self.raster), bands=selected, output=str(output))
                )
            self.assertEqual(output.read_bytes(), b"existing output")
        with self.assertRaisesRegex(ValueError, "same|match"):
            self.jobs.segment_raster(
                dict(
                    raster=str(self.raster),
                    mask=str(
                        ROOT
                        / "vendor/obia/obia/datasets/chesapeake/train_reference.tif"
                    ),
                    output=str(output),
                )
            )
        self.assertEqual(output.read_bytes(), b"existing output")

    def test_no_data_stays_zero_in_labels(self):
        with self.rasterio.open(self.raster, "r+") as dst:
            values = dst.read()
            values[:, :4, :] = -9999
            dst.write(values)
        output = self.d / "masked.gpkg"
        self.jobs.segment_raster(
            dict(
                raster=str(self.raster),
                output=str(output),
                labels=str(self.d / "masked.tif"),
                options=dict(n_segments=16, convert2lab=False),
            )
        )
        with self.rasterio.open(self.d / "masked.tif") as src:
            self.assertTrue((src.read(1)[:4] == 0).all())

    def test_cannot_overwrite_inputs_or_use_labels_as_features(self):
        before = self.objects.read_bytes()
        with self.assertRaisesRegex(ValueError, "separate"):
            self.jobs.extract_features(
                dict(
                    raster=str(self.raster),
                    objects=str(self.objects),
                    output=str(self.objects),
                )
            )
        training = self.training()
        with self.assertRaisesRegex(ValueError, "exclude"):
            self.jobs.classify_objects(
                dict(
                    objects=str(self.objects),
                    training=str(training),
                    features=["feature_class"],
                    output=str(self.d / "bad.gpkg"),
                )
            )
        self.assertEqual(self.objects.read_bytes(), before)

    def test_grouped_and_spatial_partitions_remain_disjoint(self):
        data = self.gpd.read_file(self.training())
        # Repeated paired sites each contain both classes, so grouped validation is feasible.
        data["site"] = [i // 2 for i in range(len(data))]
        data["feature_class"] = ["a" if i % 2 == 0 else "b" for i in range(len(data))]
        split = self.jobs.partition(
            data, dict(validation="grouped", group_field="site", test_fraction=0.25)
        )
        self.assertFalse(
            set(data.iloc[split.train_indices].site)
            & set(data.iloc[split.test_indices].site)
        )
        split = self.jobs.partition(
            data, dict(validation="spatial", block_size=8, test_fraction=0.25)
        )
        self.assertFalse(set(split.train_indices) & set(split.test_indices))


if __name__ == "__main__":
    unittest.main()
