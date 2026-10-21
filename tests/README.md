# Verification

Use separate interpreters for the QGIS frontend and the scientific engine.
Never install OBIA's scientific dependencies into QGIS to run these tests.
Tests create synthetic rasters and vectors, including paths with spaces and
Unicode, and use temporary QGIS profiles.

## Installer and protocol tests

With ordinary Python 3.10+:

```bash
python -m unittest discover -s tests -p test_engine_manager.py -v
python -m unittest discover -s tests -p test_worker.py -v
```

The second command skips scientific tests unless `OBIA_TEST_ENGINE=1` is set.
Installer tests cover checksums, cache reuse, ownership/removal boundaries,
repair rollback, cancellation, subprocess isolation, stale extraction caches,
Windows UTF-16 path limits, extended-path cleanup, and automatic fallback for
long Windows profiles. Actual Windows filesystem tests skip on other platforms.

## Real engine installation

Choose a dedicated, not-yet-created temporary engine root:

```bash
OBIA_ENGINE_ROOT=/tmp/obia-validation python scripts/check_engine_install.py --keep
```

On Windows, set `OBIA_ENGINE_ROOT` in the terminal environment first. The script
requires no active engine at that root, installs and repairs the real pinned
engine, cancels a further repair during package linking, verifies the previous
activation survives, and runs all scientific tests. Omit `--keep` to remove its
owned generations afterward; verified downloads remain cached.

Run scientific tests separately against an installed engine:

```python
import os, subprocess
from runtime.manager import engine_python
from runtime.client import sanitized_environment
python = engine_python()
environment = sanitized_environment(python)
environment["OBIA_TEST_ENGINE"] = "1"
subprocess.run([str(python), "-I", "-m", "unittest", "discover", "-s", "tests",
                "-p", "test_worker.py", "-v"], env=environment, check=True)
```

## Actual QGIS integration

First build the install ZIP with `python scripts/package_plugin.py`. The builder
checks its package root, required files, archive integrity, and Python syntax.
Then test the archive with QGIS's actual plugin loader in a fresh process:

```bash
python scripts/check_plugin_zip.py dist/obia_qgis.zip --qgis
```

This uses a temporary profile, discovers the extracted `obia_qgis` package,
starts it, verifies all ten Processing algorithms, and unloads it. No engine is
needed for plugin loading. Run this check against the downloaded release asset
as well as the local build. GitHub's automatic source ZIP must be rejected:
its `obia-qgis-VERSION/` folder cannot be imported as the plugin package.

With a QGIS developer environment or the QGIS application Python:

```bash
QT_QPA_PLATFORM=offscreen OBIA_TEST_QGIS=1 \
  OBIA_ENGINE_ROOT=/tmp/obia-validation \
  python -m unittest discover -s tests -p test_qgis_runtime.py -v
```

For the macOS application wrapper, supply its GDAL/PROJ data directories:

```bash
env -u PYTHONHOME -u QGIS_PREFIX_PATH -u PROJ_LIB \
  PYTHONPATH=/Applications/QGIS-final-4_2_3.app/Contents/Resources/qgis/python/plugins \
  QT_QPA_PLATFORM=offscreen OBIA_TEST_QGIS=1 \
  OBIA_ENGINE_ROOT=/private/tmp/obia-engine-test \
  GDAL_DATA=/Applications/QGIS-final-4_2_3.app/Contents/Resources/qgis/gdal \
  PROJ_DATA=/Applications/QGIS-final-4_2_3.app/Contents/Resources/qgis/proj \
  /Applications/QGIS-final-4_2_3.app/Contents/MacOS/python \
  -m unittest discover -s tests -p test_qgis_runtime.py -v
```

Change the application path for QGIS 3.40/Qt 5. Set `OBIA_PLUGIN_PATH` to an
extracted ZIP's `obia_qgis` directory to test the shipped artifact. The tests
exercise all four segmentation methods, features/NDVI/texture/shape, labelling,
both classifier outputs, real dependency self-tests, input protection, selected
memory-layer features, pending edits, and loading without scientific imports.
Both classifiers also exercise supplied test layers, alternate test class fields,
and holdout overrides. The scientific tests compare supplied-test models with
models fitted on all training data alone, independently calculate test metrics,
and change test labels to verify that those labels do not affect model fitting.

## Windows package-path audit

```bash
python scripts/download_engine_packages.py win-64 /path/to/windows-archives
python scripts/audit_windows_paths.py /path/to/windows-archives
```

The auditor uses Python 3.14's Zstandard support; older developer Python versions
need `zstandard`. It verifies all package checksums and compares every archive
member against the committed audit. For intentional lock changes use `--write`.

The CI Windows job disables Windows long-path policy on the disposable runner,
places the plugin under a long profile-like path, installs/repairs/cancels the
engine, and checks that the installer did not change that policy. Other jobs run
the engine on macOS/Linux and the shipped plugin against QGIS 3.40 and 4.2,
including the actual plugin-loader check above before engine setup. A separate
package job validates the install ZIP without requiring QGIS or an engine.
Configured CI is not evidence of a successful run.

## Local release record

Release-download verification on 2026-10-21, macOS Apple Silicon:

- Both published 0.1.5 installer assets are identical, match `SHA256SUMS`, and
  contain the expected `obia_qgis/` package. Their SHA256 is
  `6800879da0565421f00b443385ab5dc8237ce3d21ac13c93262e855d58625b68`.
- The downloaded installer passed discovery, loading, startup, registration of
  all ten algorithms, and unloading in QGIS 3.40.3 / Qt 5 and 4.2.3 / Qt 6.
- GitHub's automatic source ZIP reproduced `No module named 'obia-qgis-0'`;
  the archive checker rejects that ZIP before installation.
- Local builds were reproducible and their versioned/unversioned assets matched.
  Only installation/verification documentation differs from the published ZIP;
  its plugin and engine code is unchanged. The published assets are retained.

Verification for 0.1.5 on 2026-10-21, macOS Apple Silicon:

| Check | Result |
| --- | --- |
| Installer suite | 35 tests, OK; 2 Windows-only filesystem tests skipped |
| Packaged setup dialog | QGIS 3.40.3 setup/provider smoke test passed; dialog rendered and visually reviewed |
| Package verification | ZIP integrity, unchanged OBIA source hashes, licenses, Python syntax, and offline help anchors passed |

This release changes setup wording only. The setup introduction omits a library
version, and the engine location continues to come from the runtime's current
installation status. The release commit's Actions run covers complete engine
installation and both QGIS versions.

Verification for 0.1.4 on 2026-10-20, macOS Apple Silicon:

| Check | Result |
| --- | --- |
| Scientific engine suite | All 25 tests passed using the existing private engine |
| Packaged QGIS 3.40.3 / Qt 5 and 4.2.3 / Qt 6 | 69 tests each, OK; 25 expected skips (23 separately run scientific tests, 2 Windows-only tests) |
| Polygon inputs in Processing | Both classifiers, object labelling, and raster confusion matrices passed with selections and pending test-field edits |
| Classification dialog visibility | Point and polygon test inputs hide the holdout fraction and restore its value when cleared |

Polygon checks compare raster samples with independently intersected pixel
footprints, including polygons too small to contain a pixel centre, holes,
multipart shapes, rotated grids, reprojection, partial raster coverage, and
group attributes. Tests compare point/polygon models and validation matrices,
verify default and grouped holdouts, count matching overlaps once, and reject
conflicting labels, outside/NoData samples, or reused training/test pixels.
Object tests verify boundary intersections, conflicts, stale-label clearing,
and preservation of predictor fields. The existing OBIA source and engine
manifests are unchanged. See the release commit's Actions run for cross-platform
installation and Windows long-path verification.

Verification for 0.1.3 on 2026-10-20, Linux x64:

| Check | Result |
| --- | --- |
| Scientific engine suite | All 19 tests passed using the existing private engine |
| Packaged QGIS 4.2.3 / Qt 6 | 62 tests, OK; 19 expected skips (17 separately run scientific tests, 2 Windows-only tests) |
| Classification dialog visibility | Both classifiers passed selection, clearing, selected-feature input, prefilled test layer, and retained holdout value checks |
| Package verification | ZIP integrity, source hashes, licenses, Python syntax, and offline help links passed |

The dialog regression check also runs in the QGIS 3.40 and 4.2 CI jobs. The
local checks above do not establish their results or the cross-platform engine
installation results; see the release commit's Actions run for those checks.

Verification for 0.1.2 on 2026-10-19, macOS Apple Silicon:

| Check | Result |
| --- | --- |
| Scientific engine suite | All 19 tests passed |
| Installer suite | 35 tests, OK; 2 Windows-only filesystem tests skipped |
| Packaged QGIS 3.40.3 / Qt 5 and 4.2.3 / Qt 6 | 60 tests each, OK; 19 expected skips (17 separately run scientific tests, 2 Windows-only tests) |
| Confusion matrix dialog | Rendered and visually reviewed |

Matrix checks use known asymmetric counts to verify row/column orientation,
UTF-8 labels and raster class mappings, numeric codes, unseen observed classes,
point reprojection, duplicate handling, and rejection of outside/NoData points.
Classification HTML matrices are compared with independently calculated counts.
All 190 Windows packages retain their original pinned bytes; their installation
sequence now follows dependencies read from SHA256-verified archive metadata.
The Windows path audit was regenerated after this order-only manifest change.

Verification for 0.1.1 on 2026-10-19, macOS Apple Silicon:

| Check | Result |
| --- | --- |
| Standalone installer suite | 34 tests, OK; 2 Windows-only filesystem tests skipped |
| Scientific engine suite | All 17 tests passed, including supplied-test validation for all three classifiers |
| Packaged QGIS 3.40.3 / Qt 5 and 4.2.3 / Qt 6 | 58 tests each, OK; 17 expected skips (15 separately run scientific tests, 2 Windows-only tests) |
| Classification Processing panels | Both rendered and visually reviewed with optional test inputs |
| Manifest integrity | Simulated Windows checkout filtering retains the audited SHA256 |

CI fixes preserve manifest LF bytes, use a workspace-relative conda environment
file, compare Windows path aliases by file identity, and explicitly destroy test
layers before shutting down QGIS/GDAL. See the repository's Actions runs for the
Windows, Linux, and macOS results; local checks alone do not establish those.

Verification for 0.1.0 on 2026-10-19, macOS Apple Silicon:

| Check | Result |
| --- | --- |
| Standalone installer suite | 34 tests, OK; 2 Windows-only filesystem tests skipped |
| Scientific engine suite | All 13 tests passed, including source hashes and worker protocol |
| Real osx-arm64 installation and repair | Both passed the scientific self-test |
| Cancellation during a real package-linking repair | Previous activation/generations preserved; temporary cache removed |
| Packaged QGIS 4.2.3 / Qt 6 | 53 tests, OK; 13 expected skips (11 separately run scientific tests, 2 Windows-only tests) |
| Packaged QGIS 3.40.3 / Qt 5 | 53 tests, OK; the same 13 expected skips |
| QGIS 3.40 Processing panels and setup dialog | Rendered and visually reviewed for segmentation, features, both classifiers, and setup |
| Windows package audit | 190 SHA256-verified archives; 30,201 payload/metadata entries inspected |
| Static verification | Ruff E4/E7/E9/F and source compilation passed; bundled release hashes unchanged |

The scientific suite verifies polygon/label agreement, one-based band conversion,
all four segmentation methods, source NoData exclusion, NDVI/texture/shape,
conflicting/no-intersection labels, all three classifiers, report/mapping output,
spatial/grouped separation, input preservation, and invalid masks/bands.

For a Windows profile named `example`, the default engine layout's longest
audited extraction file is 241 UTF-16 units and its longest installed file is
193. A profile named `a very long account name for windows` would exceed the
extraction limit at the AppData location (270 units); the automatic profile-root
fallback fits at 257 units. The guard tests cover that fallback and non-BMP
Unicode path accounting. The root, package lock, and installer determine these
limits; there is no claim that arbitrary-length overrides can work.

Windows archive inspection does not execute Windows binaries. A real Windows
run, Linux execution, Intel macOS, QGIS 4.0, and production-scale workloads are
outside the local verification unless separately recorded here.
