# Release maintenance

1. Keep `vendor/obia` tied to the intended release. `SOURCE.json` records original
   hashes; the package builder refuses altered bundled source. Preserve MIT and
   PyForestScan attribution in `THIRD_PARTY_NOTICES.md`.
2. To update engine packages, increment `ENGINE_VERSION` in the manager and lock
   generator. Run `scripts/lock_engine.py /path/to/verified/micromamba`. Review
   all four manifests and their Python/OS requirements. Lock solving is a
   maintainer operation; users install only pinned manifests.
   Preserve the solver's dependency/link order. Never alphabetize package
   entries: Windows post-link scripts need their DLL dependencies installed first.
3. Download the Windows manifest with `scripts/download_engine_packages.py
   win-64 /path/to/archives`, then run `scripts/audit_windows_paths.py
   /path/to/archives --write`. The audit hashes all archives and scans both payload
   and metadata members. A changed installer checksum also requires a new audit.
4. Run installer tests, real engine install/repair/cancellation, and QGIS 3.40
   and 4.x integration tests. Test Windows with long-path policy disabled and
   the plugin installed under a long profile path. The provided CI jobs do this
   on runners; only record a pass after those jobs actually succeed.
5. Update version metadata, changelog, README, offline help, and verification
   record. Run `python scripts/package_plugin.py` and test the resulting ZIP,
   including its source hashes, licenses, and offline help links.
6. After the commit's Actions checks pass, publish a matching `vVERSION` GitHub
   release with `dist/obia_qgis-VERSION.zip` and `dist/obia_qgis.zip` attached as
   release assets. Include SHA256 checksums and verify the downloadable assets
   match the tested ZIP. GitHub's automatically generated source archives are
   not installable plugin ZIPs. Submission to the QGIS plugin directory is
   separate; this repository does not claim QGIS directory approval.

Do not move an installed conda prefix. Repairs create a new permanent generation
and change the active pointer only after the worker's real self-test succeeds.
Retain previous generations until explicit removal. Never adopt unmarked engine
folders. Installer downloads must stay HTTPS and SHA256 verified.
