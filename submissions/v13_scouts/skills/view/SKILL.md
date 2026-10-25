---
name: view
description: Bounded repository reading for the scouts - a file region with line numbers, a whole function or class by name, or an exact-text grep. Shares one reading budget across the scouts.
---

# view

Call run_skill_script with skill_name set to view, file_path set to view.py, and positional_args set to a list of strings:

- a file path, a start line and an end line, for example rich/console.py, 120, 200: prints that region with line numbers, at most 200 lines;
- def and a name, for example def, render_lines: prints the whole function or class with that name wherever it is defined;
- grep and a text, for example grep, max_width: lists the source lines containing that exact text.

Write every value as plain text without backticks. The three scouts share a budget of 18 view calls or 150 seconds; once it is used, view answers with a stop message and you must write your report at once.
