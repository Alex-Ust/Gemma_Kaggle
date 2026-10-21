---
name: check
description: Verifies your current edit in one call, in under a minute - syntax, imports, stray files, and the existing tests related to the change, each failure labelled as pre-existing or caused by the edit.
---

# check

Call run_skill_script with three arguments: skill_name set to check, file_path set to check.py, and positional_args set to a list holding one string, the names of the functions you changed. Run it after editing and before submit_patch.

It finds the existing tests that cover the changed modules and functions and runs them. To choose tests yourself, put test file paths such as tests/test_utils.py in that string instead of function names.

The report lists the changed source files, warns about scratch files and edited test files (the grader discards test edits), reports syntax errors and modules that fail to import, then shows the pytest summary and the diff of your change. When the tests are quick, each failing test is re-run on the original code: pre-existing means it fails without your change too (ignore it); your edit changed this behaviour means your change made it fail. When the tests are slow in this repository the report says so: do not run them again yourself.

Fix every SYNTAX ERROR or IMPORT FAILED line before submitting: those patches always fail.
