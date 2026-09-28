#!/bin/sh
# Build the demo sample: source EPUBs -> six glossbook runs (ds4pro) -> one merged EPUB.
# Run fetch_sources.sh first. Costs about 0.08 USD; cached results are reused.
set -e
cd "$(dirname "$0")"
python3 make_sources.py
cd books
glossbook run en.epub --target zh --level B1 --model ds4pro --yes
glossbook run ja.epub --target zh --level B1 --model ds4pro --yes
glossbook run it.epub --target en --level A2 --model ds4pro --yes
glossbook run fr.epub --target en --level B1 --model ds4pro --yes
glossbook run de.epub --target en --level B2 --model ds4pro --yes
glossbook run es.epub --target en --level C1 --no-translation --model ds4pro --yes
cd ..
python3 merge.py
