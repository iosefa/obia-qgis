# Changelog

## 0.1.3

- Hide the holdout fraction in object and pixel classification dialogs when a
  labelled test layer is supplied; restore it and its value when the layer is cleared.

## 0.1.2

- Added labelled confusion matrices to object and pixel classification reports
  for supplied-test and holdout validation.
- Added **Confusion matrix from raster**, a simple classified-raster/test-points
  dialog that exports a UTF-8 tab-separated `.txt` matrix. Reads OBIA class
  mappings, reprojects points, and samples cells without loading the whole raster.
- Published installable plugin ZIPs as GitHub release assets.
- Fixed Windows installation stalling in a package setup script by installing
  the pinned packages in dependency order; regenerated the matching path audit.

## 0.1.1

- Added optional labelled test layers and test class fields to object and pixel
  classification. Supplied test data trains on all training samples and evaluates
  only the test data; omitting it preserves the existing holdout workflow.
- Reports identify supplied-test validation, sample counts, and class coverage.
- Reject reused training/test objects or pixels and protect test input files.
- Fixed the QGIS CI environment-file path and preserved checksummed manifest
  line endings during Windows checkout.
- Corrected Windows test assertions for short path aliases and QGIS test layer
  cleanup before GDAL shutdown.

## 0.1.0

- Bundled the unchanged OBIA v0.2.0 release and its MIT notice.
- Added SLIC, Felzenszwalb, Quickshift, and watershed segmentation.
- Added spectral, NDVI, shape, and texture features; point-to-object labels;
  object and pixel classification with Random Forest, Extra Trees, or XGBoost.
- Added random, grouped, and spatial holdouts and HTML classification reports.
- Added a private engine setup dialog, checksummed package manifests, rollback,
  cancellation, offline reuse, and Windows path auditing.
- Kept analysis in the Processing Toolbox, including batch/model support.
