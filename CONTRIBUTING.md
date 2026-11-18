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
