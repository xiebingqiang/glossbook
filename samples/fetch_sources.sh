#!/bin/sh
# Download the public-domain texts of the demo sample into samples/src/.
set -e
cd "$(dirname "$0")"
mkdir -p src
for n in 46 1041 29345 22367 2000; do     # Dickens, Shakespeare, Frost, Kafka, Cervantes
  curl -sfL -o "src/pg$n.txt" "https://www.gutenberg.org/cache/epub/$n/pg$n.txt"
done
curl -sfL -o src/kumo.zip https://www.aozora.gr.jp/cards/000879/files/92_ruby_164.zip   # Akutagawa
unzip -o -q src/kumo.zip -d src
python3 wikisource.py it.wikisource.org "Le_avventure_di_Pinocchio/Capitolo_1" src/pinocchio.txt
python3 wikisource.py fr.wikisource.org "Contes_du_jour_et_de_la_nuit_(éd._Flammarion,_1885)/La_Parure" src/parure.txt
echo "Texts saved in $(pwd)/src"
