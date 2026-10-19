# Third-party notices

OBIA for QGIS is distributed under GPL-3.0-only; the full text is in LICENSE.
Copyright (C) 2026 Joseph Percival.

## OBIA 0.2.0

The unchanged release source is in `vendor/obia/obia`. Its MIT license and
copyright notice are in `vendor/obia/LICENSE`. `vendor/obia/SOURCE.json` records
the v0.2.0 Git commit and SHA256 of each bundled file. All source is retained,
including optional modules, but this plugin does not import or install OBIA's
point-cloud, deep-learning detection, notebook, or SHAP extras.

Source: https://github.com/iosefa/obia/tree/v0.2.0
Copyright (c) 2024 Joseph Emile Honour Percival.

## PyForestScan for QGIS

The engine manager, subprocess client, setup dialog, plugin lifecycle, Windows
archive auditor, installer tests, and QGIS test support are adapted from
PyForestScan for QGIS 0.4.4, commit
`62334a9aca315160bb9680e6c851c422b6d21e54`.
Copyright (C) 2026 Nicholas Rogers and Joseph Percival.
Original license: GPL-2.0-or-later. These adaptations are distributed under
GPLv3, as permitted by that license. They retain the original attribution.

Source: https://github.com/iosefa/pyforestscan-qgis

## Downloaded engine

Micromamba and conda-forge packages are downloaded separately, with pinned
HTTPS URLs, sizes, and SHA256 checksums. Each package retains its own license
and notices in its archive/installed environment. They are not part of the
plugin ZIP. The manifests and bootstrap metadata identify their sources.
