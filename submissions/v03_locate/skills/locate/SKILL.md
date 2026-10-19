---
name: locate
description: Ranks the repository's source files and functions by relevance to the issue text in one call. Use it first to find where to edit.
---

# locate

Run `scripts/locate.py` with `run_skill_script`:

- skill_name: `locate`
- file_path: `scripts/locate.py`
- args: an object with one key, `query`, whose value is the issue title followed by the exact identifiers, option names, error messages and file names that appear in the issue (keep it under 300 characters).

It prints the six most relevant source files. For each file it lists the best matching functions or classes with their line ranges, for example `fastapi/params.py: Header.__init__ L512-560`. Test files are excluded. It then prints the source (with line numbers, up to 60 lines) of the best match in the top file.

The top file is the right one about half the time and one of the six about four times in five. Read the best symbol's line range with `read_file` and confirm before editing. If nothing fits, fall back to `git grep`.
