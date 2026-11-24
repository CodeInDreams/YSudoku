# YSudoku repository instructions

Follow [CONTRIBUTING.md](CONTRIBUTING.md) for testing and release rules.

- Before every commit, review and refresh [CHANGELOG.md](CHANGELOG.md). Record user-facing features and fixes in the Unreleased section and recompute its target version when the change category changes.
- Before publishing, verify the changelog entries, runtime version, Git tag, GitHub release notes, and prerelease status against the same commit. Use the latest release, including a beta, as the numeric baseline. Omit the beta suffix when the maintainer explicitly confirms validation passed or explicitly specifies the release version. Confirm major bumps with the maintainer.
