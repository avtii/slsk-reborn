# Releasing

1. Bump the version in `pyproject.toml` and `slsk_reborn/__init__.py`, the same number in both.
2. Commit, then tag and push:
   ```sh
   git tag v0.3.0
   git push origin main v0.3.0
   ```
3. `.github/workflows/release.yml` then:
   - runs the tests and builds the executables on Windows, macOS (arm64, x64) and Linux (x64, arm64),
     running `--self-test` on each;
   - builds the wheel and sdist and checks them with `twine check`;
   - creates the GitHub release with all files attached and generated notes;
   - uploads the wheel and sdist to [PyPI](https://pypi.org/project/slsk-reborn/).

"Run workflow" on the Actions tab builds everything without releasing. The files are kept as workflow
artifacts.

## PyPI

Uploads use trusted publishing (OIDC). No token is stored in the repository. The setup, done once:

- On pypi.org, the project `slsk-reborn` has a trusted publisher: owner `avtii`, repository
  `slsk-reborn`, workflow `release.yml`, environment `pypi`.
- The GitHub repository has an environment named `pypi` and the Actions variable
  `PYPI_PUBLISH=true`. Set the variable to anything else to skip PyPI for a release.

PyPI refuses to upload a version twice. If the PyPI job fails after the GitHub release went out,
fix the cause and re-run the failed job. Don't move the tag.

## macOS signing

The macOS binaries are not signed or notarized, so users clear the quarantine flag once (see the
README). Notarizing needs a paid Apple Developer account ($99/year), a Developer ID certificate, and
`codesign` + `xcrun notarytool` steps in the macOS build job, with the certificate and an
app-specific password stored as repository secrets.
