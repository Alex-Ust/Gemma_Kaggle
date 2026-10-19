#!/bin/bash
# Copy skills from skills_src/ into every bundle that declares them.
cd "$(dirname "$0")/.."
for b in submissions/*/; do
  for s in skills_src/*/; do
    n=$(basename "$s")
    if [ -d "$b/skills/$n" ]; then rm -rf "$b/skills/$n"; cp -r "$s" "$b/skills/$n"; echo "synced $n -> $b"; fi
  done
done
find submissions -name __pycache__ -prune -exec rm -rf {} +
