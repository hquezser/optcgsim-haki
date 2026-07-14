#!/usr/bin/env bash
# Build le frontend Next.js et copie le output dans le package Python.
# À exécuter avant `python -m build` pour inclure le dashboard dans le package.

set -euo pipefail

cd "$(dirname "$0")/.."

echo "→ Build du frontend (npm run build)…"
cd frontend
npm run build

echo "→ Copie de frontend/out/ → optcgsim_tracker/static/…"
cd ..
rm -rf optcgsim_tracker/static
mkdir -p optcgsim_tracker/static
cp -r frontend/out/* optcgsim_tracker/static/

echo "✓ Frontend buildé et copié dans optcgsim_tracker/static/"
echo "  Tu peux maintenant lancer : python -m build"
