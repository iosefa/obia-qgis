# OBIA for QGIS

Object-based raster analysis in the **QGIS Processing Toolbox**, using
**OBIA 0.2.0**. Segment imagery, measure objects, label them from points or polygons, and
classify objects or pixels. Ordinary Processing dialogs support batch jobs and
models. There is no separate analysis panel and no point-cloud workflow.

**0.1.4 is experimental.** The plugin targets QGIS 3.40–3.x and 4.x.
See [the verification record](tests/README.md) for the versions and platforms
actually tested; the metadata's upper version limit is not a claim that every
release has been tested.

## Install

1. Download [obia_qgis-0.1.4.zip](https://github.com/iosefa/obia-qgis/releases/download/v0.1.4/obia_qgis-0.1.4.zip)
   from the [latest release](https://github.com/iosefa/obia-qgis/releases/latest),
   or build it with `scripts/package_plugin.sh`
   (Windows: `python scripts/package_plugin.py`).
2. In QGIS, open **Plugins → Manage and Install Plugins → Install from ZIP**,
   select the ZIP, and enable **OBIA**.
3. Open **Plugins → OBIA → Set up OBIA**, then click **Install engine**.
   Setup downloads and checks the packages, installs a private Python engine,
   and tests actual raster analysis before activating it. No terminal is needed.
4. Open **Processing → Toolbox**, search for **Check OBIA dependencies**, and run
   it. View the report in **Processing → Results Viewer**. Search for **OBIA**
   to find the analysis tools.

This follows the PyForestScan plugin's Install-from-ZIP and private-engine setup
approach. OBIA's engine supplies its scientific stack in a separate process;
it does not run pip in QGIS, alter QGIS's libraries, or change shell settings.
The ZIP bundles the unchanged OBIA v0.2.0 source, its MIT license, and offline help.
Neither sibling repository is needed to install or run it.

The initial engine installation requires internet access. Downloads use HTTPS
and pinned SHA256 checksums. An installed engine works offline on local data.
**Repair engine** validates a new generation before switching to it, keeping
the previous working installation if setup fails or is canceled. **Remove engine**
only removes this plugin's recognized engine installations; verified downloads
remain cached. Previous generations use additional space until removal.

Engine manifests cover Windows x64, Linux x64, macOS Intel, and macOS Apple
Silicon. Windows/Linux ARM engines are not supplied. The setup dialog reports
download size and required disk space. The engine uses Python 3.12; it does not
depend on the Python version embedded in QGIS. Linux packages target glibc 2.28+
and macOS packages target macOS 13+; see platform limits in the verification record.

| Engine | Initial download | Free space required for setup |
| --- | ---: | ---: |
| macOS Apple Silicon | 275 MB | 3.3 GB |
| macOS Intel | 280 MB | 3.4 GB |
| Linux x64 | 409 MB | 4.9 GB |
| Windows x64 | 439 MB | 5.3 GB |

Decimal sizes are rounded up for the pinned `0.2.0-1` engine. The tested Apple
Silicon environment occupies about 1.1 GiB, plus cached downloads.

## Windows installation and long paths

The engine lives outside the QGIS plugin/profile directory. On Windows it uses
`%LOCALAPPDATA%\obia\e`, with an existing Windows short directory name when
available. If that is too long for the pinned packages, it automatically tries
`%USERPROFILE%\.obia-e`. Generation paths and the disposable unpacking cache
are shallow. A long QGIS profile/plugin path therefore does not get repeated
inside package extraction paths.

Setup checks **every pinned package's audited maximum file and directory path**
before downloading. The audit counts Windows UTF-16 units and is bound to the
package and installer checksums. Cleanup uses Windows extended paths, including
UNC paths, so a failed installation can be retried even with deep remnants.
No administrator rights or Windows long-path registry changes are required by
the installer. Exceptionally long user-data or network paths can still exceed
third-party installer limits; setup stops before changing anything and explains
how to set `OBIA_ENGINE_ROOT` to a new, shorter folder under your control in
**Settings → Options → System → Environment**, then restart QGIS. Keep an override
in place while using an engine installed there.

The archive audit and cross-platform regression tests are included. A real
Windows installation test is configured in CI with Windows long-path policy
disabled. See the verification record for which tests have actually run.

## A simple object workflow

1. Load a local raster with a saved CRS. Start with a small clipped study area.
2. Run **SLIC segmentation**, choose bands and an approximate object count,
   and save the objects to a new GeoPackage. Optionally save the matching ID
   raster. Objects already contain band means, standard deviations, and counts.
3. Optionally run **Extract object features** for more statistics, NDVI, shape,
   or texture. Use pixel shape units for geographic rasters, or a projected CRS
   for measurements in map units.
4. Create a point or polygon layer containing a class field. Run **Label objects
   from points or polygons**. Each intersecting object takes the label, including
   boundary intersections. Objects with conflicting labels are excluded and can
   be saved separately for review. If you have separate test labels, run this
   step again with those labels to create the test objects.
5. Run **Classify objects** with the full object layer, the labelled training
   layer, its class field, and the numeric predictor fields to use. Save the
   classified GeoPackage and HTML report.

To classify pixels directly, run **Classify pixels** with the raster and labelled
points or polygons. Every pixel touched by a polygon is a sample; holes are
respected and only the polygon's overlap with the raster is sampled. Its GeoTIFF
has NoData `0` and class codes `1..K`. The HTML report and
GeoTIFF's `class_mapping` tag relate those codes to the original labels.

All band selectors use QGIS's **one-based** numbering. OBIA's output column names
retain its **zero-based** convention: `b0_mean` means the mean of QGIS band 1,
and `b3_std` means the standard deviation of QGIS band 4.

## Toolbox tools

All algorithm IDs have the prefix `obia:`. Help links open the bundled
[offline guide](docs/index.html).

| Tool | ID | Outputs |
| --- | --- | --- |
| SLIC segmentation | `slic` | Objects, optional segment-ID raster |
| Felzenszwalb segmentation | `felzenszwalb` | Objects, optional segment-ID raster |
| Quickshift segmentation | `quickshift` | Objects, optional segment-ID raster |
| Watershed segmentation | `watershed` | Objects, optional segment-ID raster |
| Extract object features | `extractfeatures` | Objects with band, NDVI, shape, texture fields |
| Label objects from points or polygons | `labelobjects` | Training/test objects, optional conflicting objects |
| Classify objects | `classifyobjects` | Classified objects and HTML report |
| Classify pixels | `classifypixels` | Class-code GeoTIFF and HTML report |
| Confusion matrix from raster | `confusionmatrix` | Tab-separated text matrix |
| Check OBIA dependencies | `checkdependencies` | HTML status report and `READY` result |

Classifiers are Random Forest, Extra Trees, and XGBoost. Both classification
tools accept an optional test layer: **Labelled test objects** for object
classification or **Labelled test points or polygons** for pixel classification. When supplied,
the model uses **all training data** and the report evaluates only the test
data. Holdout settings are ignored, and the dialog hides the holdout fraction
until the test layer is cleared. Select **Test class field** if its name
differs from the training class field. Test objects need the same predictor
fields; test points or polygons are sampled from the input raster. Test labels must occur
in training, but the test set need not contain every class. Training and test
sets must use distinct objects/pixels, even when different polygons select them.
Matching labels within either set count once per pixel. Training and test layers
can use different geometry types.

Without a test layer, advanced parameters support grouped and spatial holdouts
and distance buffers. The default is a
20% stratified random holdout; a fraction of `0` fits all samples without an
accuracy report. Holdout predictions are evaluated using only training-fitted
preprocessing, and the model is not automatically refitted on held-out data.
Random holdouts may be optimistic for neighboring samples. Reports are not an
independent map accuracy assessment. Prediction margins are probability gaps,
not calibrated accuracy estimates.

Classification reports include a **confusion matrix** whenever test data or a
holdout is used. Rows are observed classes, columns are predicted classes, and
cells contain sample counts. A model fitted on all samples without test data
has no validation matrix.

To check an existing map, run **Confusion matrix from raster**. Select a
single-band classified raster, labelled test points or polygons, their class field, and a
`.txt` output file. The file is UTF-8, tab separated, with observed class labels
in its first column and predicted class labels across the header. OBIA raster
class mappings are read automatically; for other rasters, use numeric class
codes in the test field. Labels are reprojected to the raster CRS. Polygon
sampling follows the same touched-pixel rule as classification. Outside points,
polygons with no intersecting pixels, NoData pixels, and conflicting labels in
the same pixel stop processing; matching labels count once. Only sampled raster
cells are read. Matrix counts are pixels, not polygon counts or area-weighted counts.

## Inputs and practical limits

- Rasters must be local files readable by GDAL/Rasterio with a saved CRS.
  Export web rasters and subdatasets to GeoTIFF first. Apply scale/offset
  calibration to pixel values beforehand; the plugin rejects unapplied metadata.
  Renderer colors and the current map extent do not restrict analysis.
- Vector inputs honor Processing selections, filters, and pending edits by
  staging the actual features. Geometries must be valid polygons or single points.
  Vectors are explicitly reprojected to the target raster/object CRS. An object
  layer without `segment_id` receives IDs; existing object IDs must be
  unique and non-null. Label polygons do not need object IDs or predictor fields.
- Masks must match the raster's CRS, transform, and dimensions. Nonzero valid
  mask pixels are included. Source NoData/masks are respected. Undefined features
  remain NULL; inspect them before choosing predictors.
- Watershed requires exactly one surface band. For other segmentation tools,
  selected bands are normalized independently to [0, 1]; RGB-to-Lab conversion
  is disabled so arbitrary multispectral band selections are meaningful.
- Point and polygon labels must be non-null. Boundary intersections may label
  adjacent objects. Pixel training rejects outside points, polygons with no
  intersecting pixels, NoData/masked pixels, and conflicting labels within a
  pixel; matching labels count once. Polygon attributes, including holdout group
  fields, are retained on their sampled pixels. Use grouped/spatial holdouts
  when pixels from a training area should stay together.
- Predictor fields must be numeric and present in both object and training
  layers. Exclude labels, IDs, grouping fields, and previous predictions.
- Raster loading, segmentation, feature extraction, and result arrays use memory
  for the full input area. Prediction batching does not make the whole workflow
  out-of-core. Clip/reproject rasters in QGIS before processing large scenes.
- Outputs are new GeoPackages, GeoTIFFs, and HTML reports. Input paths cannot be
  reused as outputs. Each completed file is staged before replacement, but a
  canceled multi-output job may retain a completed output or staging file.

The [API coverage map](docs/API_COVERAGE.md) explains which OBIA APIs are exposed
and which remain Python workflows. Point-cloud, deep-learning detection, SHAP,
and serialized model persistence are outside this plugin.

## Develop and verify

Use `environment.yml` for a developer QGIS environment, or run with an existing
QGIS installation's Python. Community users only need the ZIP and setup dialog.
Install/symlink the plugin under the Python package name **`obia_qgis`**, not the
hyphenated repository name. Restart QGIS after an upgrade.

See [tests/README.md](tests/README.md) for standalone installer, engine, and QGIS
tests; [docs/RELEASING.md](docs/RELEASING.md) covers package updates and release checks.

## License

The plugin is **GPL-3.0-only**, using this repository's existing [LICENSE](LICENSE).
OBIA remains **MIT** with its [original notice](vendor/obia/LICENSE) included.
This combination is compatible: MIT permits inclusion in GPL software while
requiring retention of its copyright and permission notice. QGIS permits GPLv2
or later plugins. See the [MIT terms](https://opensource.org/license/mit) and
[QGIS guidance](https://blog.qgis.org/2016/05/29/licensing-requirements-for-qgis-plugins/).

Installer/UI adaptations retain attribution to the GPL-2.0-or-later PyForestScan
plugin and are distributed here under GPLv3. Downloaded engine packages retain
their own licenses. See [third-party notices](THIRD_PARTY_NOTICES.md).
