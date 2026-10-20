---
name: check
description: Verifies your current edit in one call - syntax, imports, stray files, and the existing tests related to the changed modules, each failure labelled as pre-existing or caused by the edit.
---

# check

Call run_skill_script with skill_name check and file_path check.py, with no args. Run it after editing and before submit_patch.

With no args it finds the existing tests that import the changed modules and runs them. To choose tests yourself, pass args with one key, tests, holding space-separated pytest targets such as tests/test_utils.py::test_parse. Pass the key no-tests with value 1 to skip tests.

The report lists the changed source files, warns about scratch files and edited test files (the grader discards test edits), reports syntax errors and modules that fail to import, then shows the pytest summary. Each failing test is re-run on the original code: pre-existing means it fails without your change too (ignore it); your edit changed this behaviour means your change made it fail.

Fix every SYNTAX ERROR or IMPORT FAILED line before submitting: those patches always fail.
