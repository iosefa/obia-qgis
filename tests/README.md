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

With a QGIS developer environment or the QGIS application Python:

```bash
QT_QPA_PLATFORM=offscreen OBIA_TEST_QGIS=1 \
  OBIA_ENGINE_ROOT=/tmp/obia-validation \
  python -m unittest discover -s tests -p test_qgis_runtime.py -v
```

For the macOS application wrapper, supply its GDAL/PROJ data directories:

```bash
env -u PYTHONHOME -u PYTHONPATH -u QGIS_PREFIX_PATH -u PROJ_LIB \
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
the engine on macOS/Linux and the shipped plugin against QGIS 3.40 and 4.2.
Configured CI is not evidence of a successful run.

## Local release record

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
