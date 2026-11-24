# Contributing

Every code change must ship with unit tests.

- New solver rule, pruning path or heuristic: a focused unit test.
- Bug fix: a regression test that fails before the fix.
- UI/rendering logic: a unit test for the pure helper, or a browser check script.
- A change without a test is not ready to merge.

Run the suite with:

```bash
python3 -m unittest discover -s tests
```

## Changelog and releases

Review [CHANGELOG.md](CHANGELOG.md) before every commit. Add or update concise entries for the main user-facing changes under Unreleased, grouping them under Added, Changed, or Fixed. Internal-only changes can leave the entries unchanged. When Unreleased has entries, add a `Target version: a.b.c` line directly below its heading and recalculate it as the change set evolves.

- Fixes only, including hotfixes, increment the patch number `c`.
- Any new user-facing feature increments the minor number `b` and resets `c` to zero.
- Major changes increment `a` and reset `b` and `c` to zero. Ask the maintainer to confirm the major version before setting it.

Calculate the target for the whole batch from the previous stable release. Commits in the same batch share one target. A beta uses the target version with the `-beta` suffix. Keep this suffix for versions without full maintainer acceptance, and obtain that acceptance before publishing a stable version. An accepted beta can become the corresponding stable version with the same numbers. Published tags are immutable.

Before each release:

1. Review everything since the previous stable release against the changelog. Confirm the feature/fix classification, version, acceptance status, and release date.
2. Move the pending entries into a dated release section and update the runtime version in `ysudoku/__init__.py`. For a stable release after a beta, include the beta's user-facing changes in the stable section. Stage the changelog and version bump in the release commit.
3. Verify the release commit passes tests. Create the matching `v<version>` tag and publish a GitHub Release whose notes reflect the changelog. Mark beta releases as prereleases. Then verify the published tag, notes, and prerelease flag.
