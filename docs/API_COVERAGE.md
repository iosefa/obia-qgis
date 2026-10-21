# OBIA 0.2.0 API coverage

The entire unchanged release source is bundled. Only the following raster
workflows are imported by the isolated engine; no point-cloud dependencies
are installed.

| API family | Plugin coverage |
| --- | --- |
| `handlers.geotif.open_geotiff`, `Image` | Internal raster reader with CRS, masks, and calibration checks |
| `segmentation.create_labels`, `labels_to_segments` | Four simple region tools: SLIC/SLICO, Felzenszwalb, Quickshift, watershed |
| `segment`, `create_segments`, `create_objects` | Equivalent boundary + feature stages composed through public lower-level APIs; no duplicate toolbox entry |
| Seeded random walker, flood, snakes/active contours | Python workflows requiring seed arrays/contours; not exposed in the simple dialogs |
| `features.extract_features` | Band statistics, optional p10/p90, NDVI, all shape measurements, optional default GLCM features |
| Other spectral indices / custom texture angles, bounds, entropy radii | Python configuration; plugin exposes common settings only |
| `utils.label_segments` | Point or polygon classes assigned by intersection, mixed-object output; resets labels to handle v0.2.0 no-intersection and stale-label cases |
| `classification.classify` | Random Forest, Extra Trees, XGBoost; explicit numeric fields and supplied-test or holdout report |
| `sample_pixels`, `classify_pixels`, `ClassifiedRaster.write_geotiff` | Pixel classification with class mapping and preserved georeferencing; plugin expands polygons to touched pixel centres for the unchanged point API |
| `split_objects` | Explicit partitions for supplied test layers; random, grouped, and spatial holdouts with optional buffer |
| Confusion matrices | OBIA's validation matrices in HTML reports; Rasterio sampling at points or polygon-intersected pixels and scikit-learn counts for an existing classified map |
| `cross_validation_splits` | Python workflow; no cross-validation UI |
| Other estimators, custom pipelines, spatial class restrictions, reusable models | Python workflow |
| SHAP explanations | Optional extra omitted |
| Tiling/image enhancement/cropping helpers | Use QGIS raster tools for preparation; Python for OBIA tile workflows |
| Dataset helpers | Sample data retained with release source, no separate toolbox tool |
| Point clouds, optional detection | Outside scope; no tools or extra dependencies |

The feature extractor reprojects vectors explicitly. The GUI converts one-based
QGIS band numbers to zero-based OBIA indices and retains OBIA column names.
The wrapper explicitly passes selected-band source masks and finite-value
validity to segmentation, since OBIA 0.2.0 does not apply `Image.valid_mask` there.
Segmentation computes means, standard deviations, and valid counts only;
more expensive texture is an explicit separate feature step.
