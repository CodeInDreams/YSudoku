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

Review [CHANGELOG.md](CHANGELOG.md) before every commit. Add or update concise entries for the main user-facing changes under Unreleased, grouping them under Added, Changed, or Fixed. Internal-only changes can leave the entries unchanged. When Unreleased has entries, add a `Target version:` line directly below its heading, including the expected suffix, and recalculate it as the change set evolves.

- Fixes only, including hotfixes, increment the patch number `c`.
- Any new user-facing feature increments the minor number `b` and resets `c` to zero.
- Major changes increment `a` and reset `b` and `c` to zero. Ask the maintainer to confirm the major version before setting it.

Calculate the target for the whole batch from the latest published version, including prereleases. Commits in the same batch share one target. For example, the next fix-only batch after `1.2.0-beta` targets `1.2.1`, and the next feature batch targets `1.3.0`.

Publish without a suffix when the maintainer explicitly confirms validation passed or explicitly specifies the release version. All other releases use the `-beta` suffix and are marked as GitHub prereleases. A beta changes the release status only. Its numeric version counts normally toward the next release. Published tags are immutable.

Before each release:

1. Review everything since the previous release against the changelog. Confirm the feature/fix classification, version, acceptance or explicit version instruction, and release date.
2. Move the pending entries into a dated release section and update the runtime version in `ysudoku/__init__.py`. When publishing a stable release, cover user-facing changes since the previous stable release in its GitHub notes. Stage the changelog and version bump in the release commit.
3. Verify the release commit passes tests. Create the matching `v<version>` tag and publish a GitHub Release whose notes reflect the changelog. Mark beta releases as prereleases. Then verify the published tag, notes, and prerelease flag.
