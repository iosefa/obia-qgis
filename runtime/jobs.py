"""Raster workflows using the unchanged OBIA 0.2.0 API, outside QGIS."""

from contextlib import contextmanager, ExitStack
from html import escape
import json
import os
from pathlib import Path
import tempfile


def progress(value, message):
    print(
        json.dumps({"type": "progress", "value": value, "message": message}), flush=True
    )


def bands(values, count):
    """QGIS band numbers are one-based; OBIA's feature positions are zero-based."""
    if not values:
        return list(range(count))
    if any(
        isinstance(v, bool) or not isinstance(v, int) or not 1 <= v <= count
        for v in values
    ):
        raise ValueError(f"Band numbers must be between 1 and {count}.")
    if len(set(values)) != len(values):
        raise ValueError("Choose each band only once.")
    return [v - 1 for v in values]


@contextmanager
def image_source(path):
    import rasterio
    from obia.handlers.geotif import open_geotiff

    with rasterio.open(path) as source:
        validate_raster(source)
    image = open_geotiff(path)
    try:
        yield image
    finally:
        image.rasterio_obj.close()


def validate_raster(source):
    if source.crs is None:
        raise ValueError(
            "The raster needs a saved CRS. Assign or reproject it in QGIS first."
        )
    if any(s != 1 for s in source.scales) or any(o != 0 for o in source.offsets):
        raise ValueError(
            "Apply the raster band scale/offset to its pixel values before using OBIA."
        )
    if any("complex" in dtype for dtype in source.dtypes):
        raise ValueError("Complex-valued rasters are not supported.")


def mask_source(path, image):
    if not path:
        return None
    import numpy as np
    import rasterio

    with rasterio.open(path) as src:
        if (
            src.crs != image.crs
            or src.transform != image.transform
            or (src.height, src.width) != image.img_data.shape[:2]
        ):
            raise ValueError(
                "The mask must match the raster CRS, grid, and dimensions. Align it in QGIS first."
            )
        array = src.read(1, masked=True)
        return (
            (~np.ma.getmaskarray(array)) & np.isfinite(array.data) & (array.data != 0)
        )


def vector_source(path, kind="Polygon", crs=None, allow_empty=False):
    import geopandas as gpd
    import numpy as np

    data = gpd.read_file(path)
    if data.crs is None:
        raise ValueError("Vector inputs need a saved CRS.")
    if data.empty and not allow_empty:
        raise ValueError("The vector input has no features.")
    allowed = {
        "Point": {"Point"},
        "Polygon": {"Polygon", "MultiPolygon"},
        "Labels": {"Point", "Polygon", "MultiPolygon"},
    }[kind]
    if (
        not data.geom_type.isin(allowed).all()
        or data.geometry.is_empty.any()
        or not data.geometry.is_valid.all()
    ):
        description = "point or polygon" if kind == "Labels" else kind.lower()
        raise ValueError(
            f"Input requires valid, nonempty {description} geometries. Fix geometries in QGIS first."
        )
    if crs is not None and data.crs != crs:
        data = data.to_crs(crs)
    if not np.isfinite(data.geometry.bounds.to_numpy()).all():
        raise ValueError(
            "Vector geometries must have finite coordinates in the target CRS."
        )
    if kind == "Polygon":
        if "segment_id" not in data:
            data["segment_id"] = np.arange(1, len(data) + 1)
        if data.segment_id.isna().any() or data.segment_id.duplicated().any():
            raise ValueError("segment_id must be unique and non-null for every object.")
    return data


def raster_label_points(raster, labels):
    """Expand polygons to touched pixel centres for OBIA's unchanged point API.

    Keep source attributes (including holdout groups), and let the existing
    sampler reject invalid cells and conflicting classes and deduplicate pixels.
    A window per polygon bounds rasterization memory and handles rotated grids.
    """
    import geopandas as gpd
    import numpy as np
    import pandas as pd
    from rasterio.errors import WindowError
    from rasterio.features import geometry_mask, geometry_window
    from rasterio.transform import xy

    if labels.geom_type.eq("Point").all():
        return labels
    parts = []
    for position, geometry in enumerate(labels.geometry):
        if geometry.geom_type == "Point":
            parts.append(labels.iloc[[position]])
            continue
        try:
            window = geometry_window(raster, [geometry])
        except WindowError as exc:
            raise ValueError(
                f"Label polygon {position + 1} has no intersecting raster pixels."
            ) from exc
        touched = geometry_mask(
            [geometry],
            out_shape=(int(window.height), int(window.width)),
            transform=raster.window_transform(window),
            all_touched=True,
            invert=True,
        )
        rows, cols = np.nonzero(touched)
        if not len(rows):
            raise ValueError(
                f"Label polygon {position + 1} has no intersecting raster pixels."
            )
        xs, ys = xy(raster.transform, rows + window.row_off, cols + window.col_off)
        samples = labels.iloc[np.repeat(position, len(rows))].copy()
        samples = samples.set_geometry(gpd.points_from_xy(xs, ys, crs=raster.crs))
        parts.append(samples)
    return pd.concat(parts, ignore_index=True)


def validate_destinations(payload, names, raster_output=False):
    inputs = {
        Path(payload[k]).resolve()
        for k in ("raster", "mask", "objects", "points", "training", "test")
        if payload.get(k)
    }
    raw = [Path(payload[k]) for k in names if payload.get(k)]
    paths = [path.resolve() for path in raw]
    if len(set(paths)) != len(paths) or inputs.intersection(paths):
        raise ValueError("Choose distinct output files, separate from every input.")
    for key in names:
        if not payload.get(key):
            continue
        extension = {
            "report": ".html",
            "matrix": ".txt",
            "labels": ".tif",
            "mixed": ".gpkg",
            "output": ".tif" if raster_output else ".gpkg",
        }[key]
        if Path(payload[key]).suffix.lower() != extension:
            raise ValueError(f"Save {key} as {extension}.")
    for path in raw:
        if not path.parent.is_dir():
            raise ValueError(f"Output folder does not exist: {path.parent}")
        if path.is_symlink():
            raise ValueError("Choose a regular output path, not a symbolic link.")


@contextmanager
def staged_output(path, suffix):
    path = Path(path)
    if path.suffix.lower() != suffix:
        raise ValueError(f"Save this output as {suffix}.")
    descriptor, name = tempfile.mkstemp(prefix=".obia-", suffix=suffix, dir=path.parent)
    os.close(descriptor)
    temporary = Path(name)
    temporary.unlink()
    try:
        yield temporary
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def write_vector(data, path):
    with staged_output(path, ".gpkg") as temporary:
        data.to_file(
            temporary, driver="GPKG", layer="objects", index=False, engine="pyogrio"
        )


def write_labels(labels, image, path):
    import rasterio

    with staged_output(path, ".tif") as temporary:
        with rasterio.open(
            temporary,
            "w",
            driver="GTiff",
            width=labels.shape[1],
            height=labels.shape[0],
            count=1,
            dtype="int32",
            crs=image.crs,
            transform=image.transform,
            nodata=0,
            compress="deflate",
        ) as dst:
            dst.write(labels.astype("int32"), 1)


def segment_raster(p):
    import numpy as np
    from obia.segmentation.segment_boundaries import create_labels, labels_to_segments
    from obia.features import extract_features

    validate_destinations(p, ("output", "labels"))
    with image_source(p["raster"]) as image:
        selected = bands(p.get("bands"), image.img_data.shape[2])
        mask = mask_source(p.get("mask"), image)
        # OBIA 0.2.0's segmentation API does not consult Image.valid_mask.
        # Pass source validity explicitly, including finite values in selected bands.
        valid = np.all(image.valid_mask[:, :, selected], axis=2)
        valid &= np.all(np.isfinite(image.img_data[:, :, selected]), axis=2)
        if mask is not None:
            mask = mask & valid
        elif not valid.all():
            mask = valid
        method = p.get("method", "slic")
        options = p.get("options", {})
        if method not in {"slic", "felzenszwalb", "quickshift", "watershed"}:
            raise ValueError("Unsupported segmentation method.")
        progress(15, "Segmenting raster")
        labels = create_labels(
            image, segmentation_bands=selected, method=method, mask=mask, **options
        )
        objects = labels_to_segments(labels, image)
        if objects.empty:
            raise ValueError(
                "No objects were created. Check the raster and mask coverage."
            )
        progress(65, "Calculating band means and standard deviations")
        objects = extract_features(
            objects,
            image,
            bands=selected,
            spectral=("mean", "std", "valid_count"),
            percentiles=(),
            mask=mask,
        )
        write_vector(objects, p["output"])
        if p.get("labels"):
            write_labels(labels, image, p["labels"])
    return {
        "output": p["output"],
        "objects": len(objects),
        "labels": p.get("labels", ""),
    }


def segment_tiled_raster(p):
    """Stream buffered SLIC tiles through OBIA's unchanged label/feature APIs.

    Keep only disjoint tile cores, relabelling disconnected pieces after cropping.
    This intentionally splits objects at seams; it is not a global SLIC solution
    or the experimental checkerboard merger in obia.utils.tiling.
    """
    import numpy as np
    import rasterio
    from rasterio.windows import Window
    from skimage.measure import label
    from obia.handlers.geotif import Image
    from obia.segmentation.segment_boundaries import create_labels, labels_to_segments
    from obia.features import extract_features

    validate_destinations(p, ("output", "labels"))
    tile_size, buffer = p.get("tile_size", 512), p.get("buffer", 64)
    options = dict(p.get("options", {}))
    per_tile = options.pop("n_segments", 1000)
    for name, value, minimum in (
        ("Tile size", tile_size, 16),
        ("Overlap buffer", buffer, 0),
        ("Objects per tile", per_tile, 1),
    ):
        if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
            raise ValueError(f"{name} must be an integer of at least {minimum}.")
    if buffer >= tile_size:
        raise ValueError("Overlap buffer must be smaller than the tile size.")
    if p.get("method", "slic") != "slic":
        raise ValueError("Tiled segmentation supports SLIC only.")
    options.setdefault("convert2lab", False)

    def tile_image(data, valid, transform, crs):
        return Image(
            data,
            crs,
            [
                transform.a,
                transform.b,
                transform.d,
                transform.e,
                transform.c,
                transform.f,
            ],
            transform,
            None,
            valid,
        )

    count = 0
    # Bound GDAL's block cache as well as Python arrays. Stage both outputs until
    # all tiles finish, so a failed tile cannot replace an existing result.
    with ExitStack() as stack:
        stack.enter_context(rasterio.Env(GDAL_CACHEMAX=64 * 1024 * 1024))
        source = stack.enter_context(rasterio.open(p["raster"]))
        validate_raster(source)
        selected = bands(p.get("bands"), source.count)
        mask_source = None
        if p.get("mask"):
            mask_source = stack.enter_context(rasterio.open(p["mask"]))
            if (
                mask_source.crs != source.crs
                or mask_source.transform != source.transform
                or mask_source.shape != source.shape
            ):
                raise ValueError(
                    "The mask must match the raster CRS, grid, and dimensions. Align it in QGIS first."
                )
        objects_path = stack.enter_context(staged_output(p["output"], ".gpkg"))
        label_sink = None
        if p.get("labels"):
            labels_path = stack.enter_context(staged_output(p["labels"], ".tif"))
            label_sink = stack.enter_context(
                rasterio.open(
                    labels_path,
                    "w",
                    driver="GTiff",
                    width=source.width,
                    height=source.height,
                    count=1,
                    dtype="int32",
                    crs=source.crs,
                    transform=source.transform,
                    nodata=0,
                    compress="deflate",
                    tiled=True,
                    BIGTIFF="IF_SAFER",
                )
            )
        tiles = ((source.height + tile_size - 1) // tile_size) * (
            (source.width + tile_size - 1) // tile_size
        )
        index = 0
        for row in range(0, source.height, tile_size):
            for col in range(0, source.width, tile_size):
                index += 1
                progress(
                    5 + 90 * (index - 1) / tiles, f"Segmenting tile {index} of {tiles}"
                )
                height, width = (
                    min(tile_size, source.height - row),
                    min(tile_size, source.width - col),
                )
                core = Window(col, row, width, height)
                top, left = max(0, row - buffer), max(0, col - buffer)
                bottom = min(source.height, row + height + buffer)
                right = min(source.width, col + width + buffer)
                window = Window(left, top, right - left, bottom - top)
                pixels = source.read(
                    indexes=[b + 1 for b in selected],
                    window=window,
                    masked=True,
                    out_dtype="float32",
                )
                data = np.moveaxis(pixels.data, 0, -1)
                band_valid = np.moveaxis(~np.ma.getmaskarray(pixels), 0, -1)
                valid = np.all(band_valid & np.isfinite(data), axis=2)
                if mask_source is not None:
                    mask = mask_source.read(1, window=window, masked=True)
                    valid &= (
                        ~np.ma.getmaskarray(mask)
                        & np.isfinite(mask.data)
                        & (mask.data != 0)
                    )
                rows = slice(row - top, row - top + height)
                cols = slice(col - left, col - left + width)
                core_valid = valid[rows, cols]
                if not core_valid.any():
                    if label_sink is not None:
                        label_sink.write(
                            np.zeros((height, width), dtype="int32"), 1, window=core
                        )
                    continue
                image = tile_image(
                    data, band_valid, source.window_transform(window), source.crs
                )
                included = int(valid.sum())
                n_segments = max(
                    1, min(included, round(per_tile * included / tile_size**2))
                )
                # A single included pixel is already one object. Masked SLIC's
                # centroid initialization requires more than one sample.
                if included == 1:
                    labels = valid.astype("int32")
                else:
                    labels = create_labels(
                        image,
                        method="slic",
                        n_segments=n_segments,
                        mask=valid
                        if mask_source is not None or not valid.all()
                        else None,
                        **options,
                    )
                labels = label(labels[rows, cols], background=0, connectivity=1)
                number = int(labels.max())
                if count + number > np.iinfo(np.int32).max:
                    raise ValueError(
                        "Too many objects for segment IDs. Use fewer objects per tile."
                    )
                labels = np.where(labels > 0, labels + count, 0).astype("int32")
                image = tile_image(
                    data[rows, cols],
                    band_valid[rows, cols],
                    source.window_transform(core),
                    source.crs,
                )
                objects = labels_to_segments(labels, image)
                if not objects.empty:
                    objects = extract_features(
                        objects,
                        image,
                        spectral=("mean", "std", "valid_count"),
                        percentiles=(),
                        mask=core_valid,
                    )
                    # Only selected bands were read; retain the original OBIA
                    # band positions in field names, including reordered bands.
                    objects = objects.rename(
                        columns={
                            f"b{i}_{stat}": f"b{band}_{stat}"
                            for i, band in enumerate(selected)
                            for stat in ("mean", "std", "valid_count")
                        }
                    )
                    objects.to_file(
                        objects_path,
                        driver="GPKG",
                        layer="objects",
                        index=False,
                        engine="pyogrio",
                        mode="a" if count else "w",
                    )
                if label_sink is not None:
                    label_sink.write(labels, 1, window=core)
                count += number
        if not count:
            raise ValueError(
                "No objects were created. Check the raster and mask coverage."
            )
    progress(100, f"Created {count} objects across {tiles} tiles")
    return {
        "output": p["output"],
        "objects": count,
        "tiles": tiles,
        "labels": p.get("labels", ""),
    }


def extract_features(p):
    from obia.features import extract_features as extract, TextureConfig

    validate_destinations(p, ("output",))
    with image_source(p["raster"]) as image:
        objects = vector_source(p["objects"], crs=image.crs)
        selected = bands(p.get("bands"), image.img_data.shape[2])
        indices = {
            name: tuple(bands(values, image.img_data.shape[2]))
            for name, values in p.get("indices", {}).items()
        }
        texture = (
            TextureConfig(
                bands=tuple(selected),
                distances=(p.get("texture_distance", 1),),
                levels=p.get("texture_levels", 32),
            )
            if p.get("texture")
            else None
        )
        progress(20, "Measuring objects")
        result = extract(
            objects,
            image,
            bands=selected,
            spectral=tuple(
                p.get("statistics", ["mean", "std", "min", "max", "valid_count"])
            ),
            percentiles=(10, 90) if p.get("percentiles") else (),
            indices=indices,
            shape=p.get("shape", False),
            shape_units=p.get("shape_units", "map"),
            texture=texture,
            mask=mask_source(p.get("mask"), image),
        )
        write_vector(result, p["output"])
    return {"output": p["output"], "objects": len(result)}


def label_objects(p):
    import pandas as pd
    from obia.utils.utils import label_segments

    validate_destinations(p, ("output", "mixed"))
    objects = vector_source(p["objects"])
    points = vector_source(p["points"], kind="Labels", crs=objects.crs)
    column = p["label_field"]
    if column not in points or points[column].isna().any():
        raise ValueError(
            "Every label point or polygon needs a non-null class label in the selected field."
        )
    # Keep only the label and geometry to avoid spatial-join suffix collisions.
    points = points[[column, points.geometry.name]].rename(columns={column: "class"})
    previous_class = objects.pop("class") if "class" in objects else None
    # v0.2.0 needs this column even when no points intersect; reset stale labels.
    objects["feature_class"] = pd.Series(
        [None] * len(objects), index=objects.index, dtype=object
    )
    progress(30, "Assigning labels to intersecting objects")
    labelled, mixed_ids = label_segments(objects, points)
    if previous_class is not None:
        objects["class"] = previous_class
        labelled["class"] = previous_class.loc[labelled.index]
    mixed = objects[objects.segment_id.isin(mixed_ids)]
    write_vector(labelled, p["output"])
    if p.get("mixed"):
        write_vector(mixed, p["mixed"])
    return {
        "output": p["output"],
        "mixed": p.get("mixed", ""),
        "labelled": len(labelled),
        "conflicting": len(mixed),
    }


def classifier_options(p):
    method = p.get("method", "rf")
    if method not in {"rf", "extra_trees", "xgboost"}:
        raise ValueError("Unsupported classifier.")
    depth = p.get("max_depth", 0)
    return dict(
        method=method,
        n_estimators=p.get("trees", 200),
        max_depth=depth or (6 if method == "xgboost" else None),
        n_jobs=1,
        random_state=p.get("seed", 42),
    )


def partition(data, p):
    from obia.classification import split_objects

    fraction = p.get("test_fraction", 0.2)
    method = p.get("validation", "random")
    if method not in {"random", "grouped", "spatial"}:
        raise ValueError("Unsupported validation design.")
    return split_objects(
        data,
        method=method,
        test_size=fraction or None,
        random_state=p.get("seed", 42),
        groups=p.get("group_field") or None,
        block_size=p.get("block_size") or None,
        buffer_distance=p.get("buffer", 0),
    )


def supplied_test_partition(training, test, columns):
    """Use every training row and only supplied test rows in OBIA's explicit split."""
    import pandas as pd
    from obia.classification import split_objects

    for name, data in (("Training", training), ("Test", test)):
        missing = [column for column in columns if column not in data]
        if missing:
            raise ValueError(f"{name} data is missing predictor fields: {missing}.")
    if test.feature_class.isna().any():
        raise ValueError("Test labels cannot be missing; label every test sample.")
    unknown = test.loc[
        ~test.feature_class.isin(training.feature_class), "feature_class"
    ]
    if len(unknown):
        raise ValueError(
            f"Test classes must occur in training: {unknown.unique().tolist()}."
        )
    # Both polygon geometries and sampled pixel centres identify reused samples.
    if set(training.geometry.normalize().to_wkb()).intersection(
        test.geometry.normalize().to_wkb()
    ):
        raise ValueError(
            "Training and test data must not contain the same objects or pixels."
        )
    fields = [*columns, "feature_class", "geometry"]
    combined = pd.concat([training[fields], test[fields]], ignore_index=True)
    split = split_objects(
        combined,
        method="explicit",
        train_indices=list(range(len(training))),
        test_indices=list(range(len(training), len(combined))),
        stratify=False,  # A supplied test set need not contain every training class.
    )
    return combined, split


def write_report(result, p, mapping=None):
    if not p.get("report"):
        return
    split = result.split
    supplied = bool(p.get("test"))
    validation = "supplied test data" if supplied else p.get("validation", "random")
    test_kind = "supplied test" if supplied else "holdout"
    contents = [
        "<!doctype html><html><meta charset='utf-8'><title>OBIA classification</title>",
        "<body><h1>OBIA 0.2.0 classification</h1>",
        "<p>"
        + escape(
            f"Classifier: {p.get('method', 'rf')}. Validation: {validation}. "
            f"Training samples: {len(split.train_indices)}; {test_kind} samples: {len(split.test_indices)}."
        )
        + "</p>",
        "<pre>"
        + escape(
            result.report or "Fitted all samples. No held-out accuracy was calculated."
        )
        + "</pre>",
        "<p>All training samples were used to fit the model. Reports describe only the supplied "
        "test data, which was not used for training. Holdout settings were ignored.</p>"
        if supplied
        else "<p>Reports describe the holdout only. The model is not refitted on held-out samples. "
        "Random holdouts can be optimistic for nearby samples; choose spatial or grouped validation "
        "when assessing transfer to new areas. Probability margins are not accuracy estimates.</p>",
    ]
    contents += ["<h2>Confusion matrix</h2>"]
    if result.confusion_matrix is not None:
        contents += [
            "<p>Rows are observed test classes; columns are predicted classes. Cells are sample counts.</p>",
            matrix_table(result.confusion_matrix, result.classes).to_html(escape=True),
        ]
    else:
        contents += ["<p>No confusion matrix: no test data or holdout was used.</p>"]
    contents += [
        "<h2>Class coverage</h2>",
        split.class_counts.to_html(escape=True),
        "<h2>Settings</h2><pre>",
        escape(
            json.dumps(
                {
                    key: p.get(key)
                    for key in (
                        "method",
                        "trees",
                        "max_depth",
                        "seed",
                        "label_field",
                        "test_label_field",
                        "features",
                        "bands",
                    )
                    + (
                        ()
                        if supplied
                        else (
                            "test_fraction",
                            "validation",
                            "group_field",
                            "block_size",
                            "buffer",
                        )
                    )
                    if key in p
                },
                indent=2,
                ensure_ascii=False,
            )
        ),
        "</pre>",
    ]
    if mapping is not None:
        contents += [
            "<h2>Raster class codes</h2><p>0 is NoData.</p><pre>",
            escape(json.dumps(mapping, indent=2, ensure_ascii=False)),
            "</pre>",
        ]
    contents.append("</body></html>")
    with staged_output(p["report"], ".html") as temporary:
        temporary.write_text("\n".join(contents), encoding="utf-8")


def matrix_table(matrix, classes):
    import pandas as pd

    table = pd.DataFrame(matrix, index=classes, columns=classes)
    table.index.name = "Observed / Predicted"
    return table


def confusion_table(observed, predicted):
    """Return counts with observed classes in rows and predictions in columns."""
    from sklearn.metrics import confusion_matrix
    from sklearn.utils.multiclass import unique_labels

    classes = unique_labels(observed, predicted)
    return matrix_table(confusion_matrix(observed, predicted, labels=classes), classes)


def raster_confusion_matrix(p):
    import numpy as np
    import rasterio

    validate_destinations(p, ("matrix",))
    with rasterio.open(p["raster"]) as raster:
        if raster.count != 1 or raster.crs is None:
            raise ValueError("Choose a single-band classified raster with a saved CRS.")
        if np.issubdtype(np.dtype(raster.dtypes[0]), np.complexfloating):
            raise ValueError("Classified raster values must be integer class codes.")
        if raster.scales[0] != 1 or raster.offsets[0] != 0:
            raise ValueError(
                "Apply raster scale/offset values before evaluating class codes."
            )
        labels = vector_source(p["points"], kind="Labels", crs=raster.crs)
        field = p["label_field"]
        if field not in labels or labels[field].isna().any():
            raise ValueError(
                "Choose a test class field with a label for every point or polygon."
            )
        points = raster_label_points(raster, labels)
        rows, cols = rasterio.transform.rowcol(
            raster.transform, points.geometry.x, points.geometry.y
        )
        rows, cols = np.asarray(rows), np.asarray(cols)
        if (
            (rows < 0) | (rows >= raster.height) | (cols < 0) | (cols >= raster.width)
        ).any():
            raise ValueError(
                "Test points fall outside the classified raster. Review those points."
            )
        # Read only sampled cells, so map-wide accuracy checks need little raster memory.
        sampled = np.ma.concatenate(
            list(
                raster.sample(
                    zip(points.geometry.x, points.geometry.y), indexes=1, masked=True
                )
            )
        )
        if np.ma.getmaskarray(sampled).any() or not np.isfinite(sampled.data).all():
            raise ValueError(
                "Test labels select NoData or invalid raster pixels. Review those labels."
            )
        if not (sampled.data == np.floor(sampled.data)).all():
            raise ValueError("Classified raster values must be integer class codes.")
        predicted = [int(value) for value in sampled.data]
        mapping_text = raster.tags().get("class_mapping")
        if mapping_text:
            try:
                mapping = json.loads(mapping_text)
                predicted = [mapping[str(code)] for code in predicted]
            except (ValueError, TypeError, KeyError) as exc:
                raise ValueError(
                    "The raster class_mapping tag is invalid or missing a sampled class code."
                ) from exc
        observed = points[field].tolist()
        if any(isinstance(v, str) for v in observed + predicted) and not all(
            isinstance(v, str) for v in observed + predicted
        ):
            raise ValueError(
                "Test labels and raster classes must use the same type. Use original labels for "
                "OBIA rasters with a class_mapping tag, or numeric raster codes for other rasters."
            )
        # Retain one observation per pixel, as in OBIA's pixel classifier.
        unique, keep = {}, []
        for i, cell in enumerate(zip(rows.tolist(), cols.tolist())):
            if cell in unique and unique[cell] != observed[i]:
                raise ValueError(
                    "Conflicting test labels select the same raster pixel."
                )
            if cell not in unique:
                unique[cell] = observed[i]
                keep.append(i)
        table = confusion_table(
            [observed[i] for i in keep], [predicted[i] for i in keep]
        )
    with staged_output(p["matrix"], ".txt") as temporary:
        table.to_csv(temporary, sep="\t", encoding="utf-8", lineterminator="\n")
    return {"matrix": p["matrix"], "samples": len(keep), "classes": len(table)}


def classify_objects(p):
    from obia.classification import classify

    validate_destinations(p, ("output", "report"))
    objects = vector_source(p["objects"])
    training = vector_source(p["training"], crs=objects.crs)
    label = p.get("label_field", "feature_class")
    if label not in training:
        raise ValueError("The training class field does not exist.")
    training["feature_class"] = training[label]
    columns = p.get("features")
    forbidden = {
        label,
        p.get("test_label_field") if p.get("test") else None,
        "feature_class",
        "class",
        "segment_id",
        "fid",
        "predicted_class",
        "prediction_margin",
        p.get("group_field"),
    }
    if not columns or forbidden.intersection(columns):
        raise ValueError(
            "Select numeric predictor fields; exclude class labels, IDs, grouping fields, and previous predictions."
        )
    if p.get("test"):
        test = vector_source(p["test"], crs=objects.crs)
        test_label = p.get("test_label_field") or label
        if test_label not in test:
            raise ValueError("The test class field does not exist.")
        test["feature_class"] = test[test_label]
        training, split = supplied_test_partition(training, test, columns)
    else:
        split = partition(training, p)
    progress(25, "Training classifier and predicting objects")
    result = classify(
        objects,
        training,
        feature_columns=columns,
        split=split,
        compute_reports=bool(len(split.test_indices)),
        **classifier_options(p),
    )
    write_vector(result.classified, p["output"])
    write_report(result, p)
    return {
        "output": p["output"],
        "report": p.get("report", ""),
        "objects": len(objects),
    }


def classify_pixels(p):
    from obia.classification import classify_pixels as classify, sample_pixels

    validate_destinations(p, ("output", "report"), raster_output=True)
    with image_source(p["raster"]) as image:
        labels = vector_source(p["points"], kind="Labels", crs=image.crs)
        points = raster_label_points(image.rasterio_obj, labels)
        selected = bands(p.get("bands"), image.img_data.shape[2])
        options = dict(
            bands=selected,
            label_column=p["label_field"],
            mask=mask_source(p.get("mask"), image),
        )
        samples = sample_pixels(image, points, **options)
        if p.get("test"):
            test = raster_label_points(
                image.rasterio_obj,
                vector_source(p["test"], kind="Labels", crs=image.crs),
            )
            test_options = dict(
                options, label_column=p.get("test_label_field") or p["label_field"]
            )
            test_samples = sample_pixels(image, test, **test_options)
            points, split = supplied_test_partition(
                samples, test_samples, [f"b{band}" for band in selected]
            )
            # The combined table contains already sampled, distinct pixel centres.
            options["label_column"] = "feature_class"
        else:
            split = partition(samples, p)
        progress(25, "Training classifier and predicting pixels")
        result = classify(
            image,
            points,
            split=split,
            compute_reports=bool(len(split.test_indices)),
            **options,
            **classifier_options(p),
        )
        with staged_output(p["output"], ".tif") as temporary:
            result.write_geotiff(temporary)
        mapping = {
            str(code): value.item() if hasattr(value, "item") else value
            for code, value in result.class_mapping.items()
        }
        write_report(result, p, mapping)
    return {
        "output": p["output"],
        "report": p.get("report", ""),
        "class_mapping": mapping,
    }


def selftest(_):
    import geopandas as gpd
    import numpy as np
    import rasterio
    import sklearn
    import skimage
    import xgboost
    from rasterio.transform import from_origin
    from shapely.geometry import Point

    with tempfile.TemporaryDirectory(prefix="obia-check-") as directory:
        d = Path(directory)
        raster = d / "input.tif"
        yy, xx = np.mgrid[:24, :24]
        with rasterio.open(
            raster,
            "w",
            driver="GTiff",
            width=24,
            height=24,
            count=1,
            dtype="float32",
            crs="EPSG:32605",
            transform=from_origin(100, 200, 1, 1),
        ) as dst:
            dst.write((xx + (xx >= 12) * 50 + yy / 100).astype("float32"), 1)
        segment_raster(
            dict(
                raster=str(raster),
                output=str(d / "objects.gpkg"),
                labels=str(d / "labels.tif"),
                options=dict(n_segments=16, compactness=1, convert2lab=False),
            )
        )
        extract_features(
            dict(
                raster=str(raster),
                objects=str(d / "objects.gpkg"),
                output=str(d / "features.gpkg"),
                shape=True,
                texture=True,
            )
        )
        objects = gpd.read_file(d / "features.gpkg")
        points = gpd.GeoDataFrame(
            {
                "class": [
                    "low" if p.x < 112 else "high"
                    for p in objects.representative_point()
                ]
            },
            geometry=objects.representative_point(),
            crs=objects.crs,
        )
        points.to_file(d / "points.gpkg", driver="GPKG", index=False)
        label_objects(
            dict(
                objects=str(d / "features.gpkg"),
                points=str(d / "points.gpkg"),
                label_field="class",
                output=str(d / "training.gpkg"),
                mixed=str(d / "mixed.gpkg"),
            )
        )
        classify_objects(
            dict(
                objects=str(d / "features.gpkg"),
                training=str(d / "training.gpkg"),
                features=["b0_mean"],
                output=str(d / "classes.gpkg"),
                trees=5,
                test_fraction=0,
            )
        )
        # Also exercise the separately linked XGBoost runtime, raster writer, and class mapping.
        pixel_points = gpd.GeoDataFrame(
            {"class": ["low", "low", "high", "high"]},
            geometry=[
                Point(102.5, 197.5),
                Point(103.5, 195.5),
                Point(120.5, 197.5),
                Point(121.5, 195.5),
            ],
            crs=objects.crs,
        )
        pixel_points.to_file(d / "pixels.gpkg", driver="GPKG", index=False)
        result = classify_pixels(
            dict(
                raster=str(raster),
                points=str(d / "pixels.gpkg"),
                label_field="class",
                output=str(d / "classes.tif"),
                report=str(d / "report.html"),
                method="xgboost",
                trees=5,
                test_fraction=0,
            )
        )
        with rasterio.open(result["output"]) as src:
            if src.crs != objects.crs or src.nodata != 0 or not np.any(src.read(1) > 0):
                raise RuntimeError("Raster classification self-test failed.")
    return {
        "ready": True,
        "obia": "0.2.0",
        "numpy": np.__version__,
        "rasterio": rasterio.__version__,
        "geopandas": gpd.__version__,
        "scikit_learn": sklearn.__version__,
        "scikit_image": skimage.__version__,
        "xgboost": xgboost.__version__,
    }


def dispatch(operation, payload):
    operations = {
        "segment": segment_raster,
        "segment_tiled": segment_tiled_raster,
        "features": extract_features,
        "label": label_objects,
        "classify_objects": classify_objects,
        "classify_pixels": classify_pixels,
        "confusion_matrix": raster_confusion_matrix,
        "selftest": selftest,
    }
    if operation not in operations:
        raise ValueError(f"Unknown OBIA operation: {operation}")
    result = operations[operation](payload)
    progress(100, "Finished")
    return result
