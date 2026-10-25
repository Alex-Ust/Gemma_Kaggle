---
name: locate
description: Ranks the repository's source files and functions by relevance to the issue text in one call and prints the source of the best match. Use it as your first call.
---

# locate

Call run_skill_script with skill_name set to locate, file_path set to locate.py, and positional_args set to a list holding one string, the search query. The query is the issue title followed by the exact identifiers, option names, error messages and file names from the issue, under 300 characters. Write every value as plain text without backticks.

It prints the six most relevant source files. For each file it lists the best matching functions or classes with their line ranges, for example fastapi/params.py: Header.__init__ L512-560. Test files are excluded. It then prints, with line numbers, the source of the two best matches in the top file and the best match in the second file.

The top file is the right one about half the time and one of the six about four times in five. If the printed source is what the issue is about, do not read it again. If nothing fits, use git grep -n -F with an exact name from the issue.
