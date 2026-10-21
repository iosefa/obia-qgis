"""Scientific integration tests run with the installed engine's Python."""

import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

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
                self.assertIn("<h2>Confusion matrix</h2>", report.read_text())

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
        self.assertIn("No confusion matrix", report.read_text())

    def supplied_test_data(self, pixels=False):
        data = self.gpd.read_file(self.points() if pixels else self.training())
        label = "cover" if pixels else "feature_class"
        test = data.groupby(label, sort=False).head(2).copy()
        training = data.drop(test.index).copy()
        training_path, test_path = self.d / "train-subset.gpkg", self.d / "test.gpkg"
        training.to_file(training_path, index=False)
        test = test.rename(columns={label: "observed"})
        test.to_file(test_path, index=False)
        payload = dict(
            label_field=label,
            test=str(test_path),
            test_label_field="observed",
            trees=8,
            # These holdout settings must have no effect when test data is given.
            test_fraction=0.9,
            validation="grouped",
            group_field="absent",
            buffer=100000,
            report=str(self.d / "independent.html"),
        )
        if pixels:
            payload.update(
                raster=str(self.raster),
                points=str(training_path),
                bands=[2],
                output=str(self.d / "independent.tif"),
            )
        else:
            payload.update(
                objects=str(self.objects),
                training=str(training_path),
                features=["b0_mean", "b1_mean"],
                output=str(self.d / "independent.gpkg"),
            )
        return payload, training, test

    def test_supplied_test_data_trains_all_and_reports_only_test_predictions(self):
        from sklearn.metrics import classification_report
        from obia.classification import sample_pixels

        for pixels in (False, True):
            for method in ("rf", "extra_trees", "xgboost"):
                with self.subTest(pixels=pixels, method=method):
                    payload, training, test = self.supplied_test_data(pixels)
                    payload["method"] = method
                    run = (
                        self.jobs.classify_pixels
                        if pixels
                        else self.jobs.classify_objects
                    )
                    if pixels:
                        with self.jobs.image_source(self.raster) as image:
                            test = sample_pixels(
                                image, test, bands=[1], label_column="observed"
                            )
                    with patch.object(
                        self.jobs, "write_report", wraps=self.jobs.write_report
                    ) as report:
                        run(payload)
                    result = report.call_args.args[0]
                    self.assertEqual(len(result.split.train_indices), len(training))
                    self.assertEqual(len(result.split.test_indices), len(test))
                    self.assertEqual(len(result.split.excluded_indices), 0)
                    expected = classification_report(
                        test.observed,
                        result.model.predict(test[list(result.feature_columns)]),
                        labels=result.classes,
                        zero_division=0,
                    )
                    self.assertEqual(result.report, expected)
                    from sklearn.metrics import confusion_matrix

                    expected_matrix = confusion_matrix(
                        test.observed,
                        result.model.predict(test[list(result.feature_columns)]),
                        labels=result.classes,
                    )
                    self.np.testing.assert_array_equal(
                        result.confusion_matrix, expected_matrix
                    )
                    text = Path(payload["report"]).read_text()
                    self.assertIn(
                        self.jobs.matrix_table(expected_matrix, result.classes).to_html(
                            escape=True
                        ),
                        text,
                    )
                    self.assertIn(
                        f"Training samples: {len(training)}; supplied test samples: {len(test)}",
                        text,
                    )
                    self.assertIn("Holdout settings were ignored", text)
                    # A supplied test set must produce the same fitted model as training
                    # on these training data alone. Changing test labels must not train it.
                    baseline = dict(
                        payload,
                        test=None,
                        test_fraction=0,
                        validation="random",
                        group_field=None,
                        buffer=0,
                    )
                    with patch.object(
                        self.jobs, "write_report", wraps=self.jobs.write_report
                    ) as report:
                        run(baseline)
                    all_training = report.call_args.args[0]
                    features = test[list(result.feature_columns)]
                    self.np.testing.assert_array_equal(
                        result.model.predict_proba(features),
                        all_training.model.predict_proba(features),
                    )
                    test = self.gpd.read_file(payload["test"])
                    test["observed"] = test.observed.map(
                        {"forest": "water", "water": "forest"}
                    )
                    test.to_file(payload["test"], index=False)
                    with patch.object(
                        self.jobs, "write_report", wraps=self.jobs.write_report
                    ) as report:
                        run(payload)
                    changed = report.call_args.args[0]
                    self.assertNotEqual(result.report, changed.report)
                    self.np.testing.assert_array_equal(
                        result.model.predict_proba(features),
                        changed.model.predict_proba(features),
                    )

    def test_supplied_test_data_can_use_training_field_and_a_subset_of_classes(self):
        for pixels in (False, True):
            with self.subTest(pixels=pixels):
                p, _, test = self.supplied_test_data(pixels)
                test = test[test.observed == "forest"].rename(
                    columns={"observed": p["label_field"]}
                )
                test.to_file(p["test"], index=False)
                p.pop("test_label_field")
                run = (
                    self.jobs.classify_pixels if pixels else self.jobs.classify_objects
                )
                run(p)
                self.assertIn("supplied test samples: 2", Path(p["report"]).read_text())

    def test_invalid_supplied_test_data_preserves_outputs(self):
        for pixels in (False, True):
            with self.subTest(pixels=pixels):
                p, training, test = self.supplied_test_data(pixels)
                run = (
                    self.jobs.classify_pixels if pixels else self.jobs.classify_objects
                )
                Path(p["output"]).write_bytes(b"existing output")
                variants = [
                    (test.assign(observed="unseen"), "occur in training"),
                    (test.assign(observed=None), "missing"),
                    (
                        training.rename(columns={p["label_field"]: "observed"}),
                        "same objects or pixels",
                    ),
                    (test.drop(columns="observed"), "class field|column"),
                ]
                if not pixels:
                    variants.append((test.drop(columns="b0_mean"), "missing predictor"))
                for invalid, message in variants:
                    invalid.to_file(p["test"], index=False)
                    with self.assertRaisesRegex(ValueError, message):
                        run(p)
                    self.assertEqual(Path(p["output"]).read_bytes(), b"existing output")
                before = Path(p["test"]).read_bytes()
                with self.assertRaisesRegex(ValueError, "separate"):
                    run(dict(p, output=p["test"]))
                self.assertEqual(Path(p["test"]).read_bytes(), before)

    def test_pixel_default_still_reserves_a_holdout(self):
        with patch.object(
            self.jobs, "write_report", wraps=self.jobs.write_report
        ) as report:
            self.jobs.classify_pixels(
                dict(
                    raster=str(self.raster),
                    points=str(self.points()),
                    label_field="cover",
                    trees=5,
                    output=str(self.d / "holdout.tif"),
                    report=str(self.d / "holdout.html"),
                )
            )
        split = report.call_args.args[0].split
        self.assertEqual(len(split.train_indices), 12)
        self.assertEqual(len(split.test_indices), 4)
        self.assertIn("holdout samples: 4", (self.d / "holdout.html").read_text())

    def polygon_labels(self, points):
        """Small polygons around points, all within their original raster cells."""
        from rasterio.transform import rowcol, xy

        polygons = points.copy()
        rows, cols = rowcol(self.transform, points.geometry.x, points.geometry.y)
        xs, ys = xy(self.transform, rows, cols)
        polygons.geometry = self.gpd.points_from_xy(xs, ys, crs=points.crs)
        polygons.geometry = polygons.geometry.buffer(0.2, cap_style=3)
        return polygons

    def test_polygon_pixel_intersections_holes_multipart_reprojection_and_groups(self):
        from affine import Affine
        from obia.classification import sample_pixels
        from shapely.affinity import affine_transform
        from shapely.geometry import MultiPolygon, Polygon, box

        shapes = [
            Polygon(
                box(0.1, 0.1, 5.9, 5.9).exterior.coords,
                [box(1.1, 1.1, 4.9, 4.9).exterior.coords],
            ),
            MultiPolygon([box(20.1, 2.1, 20.2, 2.2), box(23.1, 4.1, 23.2, 4.2)]),
            box(-1.2, 10.2, 0.2, 11.2),  # Clip to the raster, not the polygon centre.
        ]
        for transform in (self.transform, self.transform * Affine.rotation(17)):
            with self.subTest(transform=transform):
                with self.rasterio.open(self.raster, "r+") as raster:
                    raster.transform = transform
                geometries = [
                    affine_transform(
                        g,
                        [
                            transform.a,
                            transform.b,
                            transform.d,
                            transform.e,
                            transform.c,
                            transform.f,
                        ],
                    )
                    for g in shapes
                ]
                labels = self.gpd.GeoDataFrame(
                    {
                        "cover": ["forest", "water", "forest"],
                        "site": [1, 2, 3],
                        "segment_id": [1, 1, 1],
                    },
                    geometry=geometries,
                    crs=32605,
                )
                path = self.d / "polygon labels.gpkg"
                labels.to_crs(4326).to_file(path, index=False)
                labels = self.jobs.vector_source(path, kind="Labels", crs=32605)
                with self.jobs.image_source(self.raster) as image:
                    points = self.jobs.raster_label_points(image.rasterio_obj, labels)
                    sampled = sample_pixels(
                        image, points, bands=[1], label_column="cover"
                    )
                expected = {}
                for i, shape in enumerate(shapes):
                    for row in range(32):
                        for col in range(32):
                            if shape.intersects(box(col, row, col + 1, row + 1)):
                                expected[(row, col)] = (
                                    labels.cover.iloc[i],
                                    labels.site.iloc[i],
                                )
                actual = {
                    (s.pixel_row, s.pixel_col): (s.feature_class, s.site)
                    for s in sampled.itertuples()
                }
                self.assertEqual(actual, expected)
                self.assertEqual(len(sampled), 36)
                self.assertNotIn((2, 2), actual)  # A pixel wholly inside the hole.
                self.assertIn((2, 20), actual)  # Polygon does not contain its centre.
                self.np.testing.assert_array_equal(
                    sampled.b1,
                    (self.values * 2 + 10)[sampled.pixel_row, sampled.pixel_col],
                )

    def test_polygon_and_point_training_test_combinations_match_point_models(self):
        for training_polygons, test_polygons in (
            (True, True),
            (True, False),
            (False, True),
        ):
            with self.subTest(
                training_polygons=training_polygons, test_polygons=test_polygons
            ):
                p, training, test = self.supplied_test_data(pixels=True)
                with patch.object(
                    self.jobs, "write_report", wraps=self.jobs.write_report
                ) as report:
                    self.jobs.classify_pixels(p)
                baseline = report.call_args.args[0]
                if training_polygons:
                    self.polygon_labels(training).to_crs(4326).to_file(
                        p["points"], index=False
                    )
                if test_polygons:
                    self.polygon_labels(test).to_file(p["test"], index=False)
                with patch.object(
                    self.jobs, "write_report", wraps=self.jobs.write_report
                ) as report:
                    self.jobs.classify_pixels(p)
                result = report.call_args.args[0]
                self.assertEqual(len(result.split.train_indices), len(training))
                self.assertEqual(len(result.split.test_indices), len(test))
                self.np.testing.assert_array_equal(
                    result.classified, baseline.classified
                )
                self.np.testing.assert_array_equal(
                    result.confusion_matrix, baseline.confusion_matrix
                )
                self.assertEqual(result.report, baseline.report)

    def test_polygon_holdout_uses_all_intersecting_pixels_and_preserves_groups(self):
        from shapely.geometry import box

        labels = self.gpd.GeoDataFrame(
            {"cover": ["forest", "water"] * 4, "site": [0, 0, 1, 1, 2, 2, 3, 3]},
            geometry=[
                box(x, y, x + 1.4, y + 1.4)
                for y in (170.2, 176.2, 182.2, 188.2)
                for x in (102.2, 122.2)
            ],
            crs=32605,
        )
        path = self.d / "polygon holdout.gpkg"
        labels.to_file(path, index=False)
        p = dict(
            raster=str(self.raster),
            points=str(path),
            label_field="cover",
            trees=5,
            output=str(self.d / "polygons.tif"),
            report=str(self.d / "polygons.html"),
        )
        for options in (
            {},
            dict(validation="grouped", group_field="site", test_fraction=0.25),
        ):
            with patch.object(
                self.jobs, "write_report", wraps=self.jobs.write_report
            ) as report:
                self.jobs.classify_pixels(dict(p, **options))
            result = report.call_args.args[0]
            self.assertEqual(len(result.samples), 32)  # Four pixels per polygon.
            self.assertGreater(len(result.split.test_indices), 0)
            self.assertEqual(
                len(result.split.train_indices) + len(result.split.test_indices), 32
            )
            if options:
                self.assertFalse(
                    set(result.samples.iloc[result.split.train_indices].site)
                    & set(result.samples.iloc[result.split.test_indices].site)
                )

    def test_invalid_polygon_samples_and_train_test_reuse_preserve_outputs(self):
        import pandas as pd
        from shapely.geometry import box

        points = self.gpd.read_file(self.points())
        labels = self.polygon_labels(points)
        path = self.d / "polygons.gpkg"
        output = self.d / "polygons.tif"
        output.write_bytes(b"existing raster")
        p = dict(
            raster=str(self.raster),
            points=str(path),
            label_field="cover",
            trees=5,
            output=str(output),
            test_fraction=0,
        )
        conflict = labels.iloc[[0]].copy()
        conflict["cover"] = "conflict"
        outside = labels.copy()
        outside.loc[0, "geometry"] = box(999, 999, 1000, 1000)
        invalid = labels.copy()
        invalid.loc[0, "geometry"] = box(100.1, 199.1, 100.9, 199.9)
        with self.rasterio.open(self.raster, "r+") as raster:
            values = raster.read()
            values[:, 0, 0] = -9999
            raster.write(values)
        for data, message in (
            (pd.concat([labels, conflict], ignore_index=True), "Conflicting"),
            (outside, "no intersecting"),
            (invalid, "invalid pixels"),
            (labels.assign(cover=None), "missing"),
        ):
            data.to_file(path, index=False)
            with self.assertRaisesRegex(ValueError, message):
                self.jobs.classify_pixels(p)
            self.assertEqual(output.read_bytes(), b"existing raster")
        labels.to_file(path, index=False)
        points.to_file(self.d / "test points.gpkg", index=False)
        with self.assertRaisesRegex(ValueError, "same objects or pixels"):
            self.jobs.classify_pixels(dict(p, test=str(self.d / "test points.gpkg")))
        self.assertEqual(output.read_bytes(), b"existing raster")
        # Matching overlaps are retained once, as for duplicate points.
        pd.concat([labels, labels], ignore_index=True).to_file(path, index=False)
        with patch.object(
            self.jobs, "write_report", wraps=self.jobs.write_report
        ) as report:
            self.jobs.classify_pixels(p)
        self.assertEqual(len(report.call_args.args[0].samples), len(points))

    def test_object_polygon_intersections_assign_labels_and_exclude_conflicts(self):
        from shapely.geometry import box

        objects = self.gpd.GeoDataFrame(
            {
                "segment_id": [1, 2, 3, 4],
                "feature_class": ["stale"] * 4,
                "class": [99] * 4,
            },
            geometry=[box(x, 170, x + 4, 174) for x in (100, 104, 108, 112)],
            crs=32605,
        )
        objects.to_file(self.objects, index=False)
        labels = self.gpd.GeoDataFrame(
            {"cover": ["forest", "water"]},
            # First touches objects 1 and 2; second spans objects 2 and 3.
            geometry=[box(101, 171, 104, 172), box(107, 171, 110, 172)],
            crs=32605,
        )
        path = self.d / "label polygons.gpkg"
        labels.to_file(path, index=False)
        p = dict(
            objects=str(self.objects),
            points=str(path),
            label_field="cover",
            output=str(self.d / "labelled.gpkg"),
            mixed=str(self.d / "mixed.gpkg"),
        )
        result = self.jobs.label_objects(p)
        self.assertEqual(result["conflicting"], 1)
        data = self.gpd.read_file(p["output"])
        self.assertEqual(
            dict(zip(data.segment_id, data.feature_class)), {1: "forest", 3: "water"}
        )
        self.assertEqual(data["class"].tolist(), [99, 99])
        self.assertEqual(self.gpd.read_file(p["mixed"]).segment_id.tolist(), [2])
        labels["cover"] = "forest"
        labels.to_crs(4326).to_file(path, index=False)
        result = self.jobs.label_objects(p)
        self.assertEqual(result["labelled"], 3)
        self.assertEqual(result["conflicting"], 0)

    def confusion_inputs(self, mapped=False):
        from rasterio.transform import xy
        from shapely.geometry import Point

        raster = self.d / "class codes.tif"
        with self.rasterio.open(
            raster,
            "w",
            driver="GTiff",
            width=3,
            height=2,
            count=1,
            dtype="uint8",
            crs="EPSG:32605",
            transform=self.transform,
            nodata=0,
        ) as dst:
            dst.write(self.np.array([[1, 2, 2], [2, 1, 0]], dtype="uint8"), 1)
            if mapped:
                dst.update_tags(class_mapping=json.dumps({"1": "forêt", "2": "water"}))
        labels = (
            ["forêt", "forêt", "forêt", "water", "unseen"]
            if mapped
            else [1, 1, 1, 2, 3]
        )
        points = self.gpd.GeoDataFrame(
            {"truth": labels},
            geometry=[
                Point(*xy(self.transform, row, col))
                for row, col in ((0, 0), (0, 1), (0, 2), (1, 0), (1, 1))
            ],
            crs="EPSG:32605",
        ).to_crs(4326)
        path = self.d / "test reference.gpkg"
        points.to_file(path, index=False)
        return dict(
            raster=str(raster),
            points=str(path),
            label_field="truth",
            matrix=str(self.d / "matrix.txt"),
        ), points

    def test_raster_confusion_matrix_counts_orientation_mapping_and_reprojection(self):
        import pandas as pd

        for mapped in (False, True):
            with self.subTest(mapped=mapped):
                payload, points = self.confusion_inputs(mapped)
                # Identically labelled duplicates must not inflate sample counts.
                pd.concat([points, points.iloc[[0]]], ignore_index=True).to_file(
                    payload["points"], index=False
                )
                result = call_with_python(sys.executable, "confusion_matrix", payload)
                self.assertEqual(result["samples"], 5)
                text = Path(payload["matrix"]).read_text(encoding="utf-8")
                self.assertTrue(text.startswith("Observed / Predicted\t"))
                table = pd.read_csv(payload["matrix"], sep="\t", index_col=0)
                expected = (
                    [[1, 0, 2], [1, 0, 0], [0, 0, 1]]
                    if mapped
                    else [[1, 2, 0], [0, 1, 0], [1, 0, 0]]
                )
                self.np.testing.assert_array_equal(table.to_numpy(), expected)
                self.assertEqual(
                    table.columns.tolist(),
                    ["forêt", "unseen", "water"] if mapped else ["1", "2", "3"],
                )

    def test_raster_confusion_matrix_invalid_points_preserve_existing_output(self):
        import pandas as pd
        from shapely.geometry import Point

        p, points = self.confusion_inputs()
        output = Path(p["matrix"])
        output.write_bytes(b"existing matrix")
        conflict = points.iloc[[0]].copy()
        conflict["truth"] = 2
        outside = points.to_crs(32605)
        outside.loc[0, "geometry"] = Point(999, 999)
        nodata = points.to_crs(32605)
        nodata.loc[0, "geometry"] = Point(102.5, 198.5)
        for invalid, message in (
            (pd.concat([points, conflict], ignore_index=True), "Conflicting"),
            (outside, "outside"),
            (nodata, "NoData"),
            (points.assign(truth=None), "label for every"),
            (points.assign(truth="forest"), "same type"),
        ):
            invalid.to_file(p["points"], index=False)
            with self.assertRaisesRegex(ValueError, message):
                self.jobs.raster_confusion_matrix(p)
            self.assertEqual(output.read_bytes(), b"existing matrix")
        with self.assertRaisesRegex(ValueError, "separate"):
            self.jobs.raster_confusion_matrix(dict(p, matrix=p["raster"]))

    def test_raster_confusion_matrix_samples_polygon_intersections_once(self):
        import pandas as pd
        from shapely.geometry import box

        p, _ = self.confusion_inputs(mapped=True)
        labels = self.gpd.GeoDataFrame(
            {"truth": ["forêt", "water", "forêt"]},
            geometry=[
                box(100.1, 199.1, 102.9, 199.9),
                box(100.1, 198.1, 101.9, 198.9),
                box(100.2, 199.2, 100.8, 199.8),
            ],
            crs=32605,
        )
        labels.to_crs(4326).to_file(p["points"], index=False)
        result = self.jobs.raster_confusion_matrix(p)
        self.assertEqual(result["samples"], 5)
        table = pd.read_csv(p["matrix"], sep="\t", index_col=0)
        self.assertEqual(table.columns.tolist(), ["forêt", "water"])
        self.np.testing.assert_array_equal(table.to_numpy(), [[1, 2], [1, 1]])
        before = Path(p["matrix"]).read_bytes()
        labels.loc[1, "geometry"] = box(100.1, 198.1, 102.9, 198.9)
        labels.to_file(p["points"], index=False)
        with self.assertRaisesRegex(ValueError, "NoData"):
            self.jobs.raster_confusion_matrix(p)
        self.assertEqual(Path(p["matrix"]).read_bytes(), before)

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
