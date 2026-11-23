# Adding an HLK family

1. Copy `families/_template/` to `families/<your_family>/` and add the family's name to `FAMILIES` in `__init__.py`.
2. Set `GROUP` (naming, language or control) and `STRESSOR` (one line). The group is fixed before any run.
3. Write `make(seed)`: one or two throwaway repositories (Python standard library and `unittest` only, names from
   `common.NAMES`), the user's turns (`spoken` words, the `canonical` typed form, a trigger), slot answers for the
   questions a sensible harness may ask, hidden tests, the solved files, and the protected paths. Everything comes
   from the seed. Use `py()` and `hidden_test()` so every file carries the canary.
4. Run `uv run --locked python bench/conversational/hlk/run.py verify` (free, no keys): the check must fail on the
   untouched repository and pass with the solved files, and three seeds must regenerate byte-identical.
5. Open a pull request with `git commit -s`. Accepted authors are named on the results page. No prizes, no filter step:
   a family is not selected on how any system scores on it.

Synthetic data only: invented names, no personal data, nothing from a live session. Text CC BY 4.0, code MIT.
