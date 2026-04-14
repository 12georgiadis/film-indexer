#!/bin/bash
# run_pipeline.sh — full pipeline launcher for Goldberg
#
# Usage :
#   ./run_pipeline.sh scan      # Phase 0 : inventory scan
#   ./run_pipeline.sh batch     # Phase 3 : async Gemini analysis
#   ./run_pipeline.sh patch     # Phase 4 : FCPXML patch
#   ./run_pipeline.sh stats     # SQLite stats
#
# Runs on Nomad via SSH. Assumes :
# - C:\Goldberg\vo-pipeline\.venv (Python 3.11 venv)
# - C:\Goldberg\film-indexer\ (cloned repo)
# - C:\Goldberg\vo-pipeline\.env (GEMINI_API_KEY)

set -e

NOMAD_USER="ismael"
NOMAD_IP="192.168.4.43"
NOMAD_VENV="C:\\Goldberg\\vo-pipeline\\.venv\\Scripts\\python.exe"
NOMAD_REPO="C:\\Goldberg\\film-indexer"
NOMAD_DB="C:\\Goldberg\\film-indexer\\state.db"
NOMAD_OUT="C:\\Goldberg\\film-indexer\\output"
NOMAD_ENV="C:\\Goldberg\\vo-pipeline\\.env"

COMMAND="${1:-help}"

case "$COMMAND" in
    scan)
        echo "Phase 0 : scanning drives..."
        ssh $NOMAD_USER@$NOMAD_IP "powershell -NoProfile -Command \"cd $NOMAD_REPO; git pull; $NOMAD_VENV film_indexer\\scan_drives.py --roots F:\\ G:\\ --since 2026-02-18 --db $NOMAD_DB\""
        ;;
    batch)
        LIMIT="${2:-20}"
        WORKERS="${3:-6}"
        BUDGET="${4:-30.0}"
        echo "Phase 3 : async batch limit=$LIMIT workers=$WORKERS budget=\$$BUDGET"
        ssh $NOMAD_USER@$NOMAD_IP "powershell -NoProfile -Command \"cd $NOMAD_REPO; git pull; \$env:GEMINI_API_KEY = ((Get-Content $NOMAD_ENV | Select-String GEMINI_API_KEY) -split '=')[1].Trim(); $NOMAD_VENV -u film_indexer\\async_pipeline.py --db $NOMAD_DB --out $NOMAD_OUT --limit $LIMIT --workers $WORKERS --budget-cap $BUDGET\""
        ;;
    patch)
        SOURCE_XML="${2:?Usage: patch <source.fcpxml> [output.fcpxml]}"
        OUTPUT_XML="${3:-${SOURCE_XML%.fcpxml}_indexed.fcpxml}"
        echo "Phase 4 : patching $SOURCE_XML → $OUTPUT_XML"
        ssh $NOMAD_USER@$NOMAD_IP "$NOMAD_VENV -c \"import sys; sys.path.insert(0, r'$NOMAD_REPO'); from film_indexer.lib.fcpxml_patcher import patch_fcpxml; from pathlib import Path; stats = patch_fcpxml(Path(r'$SOURCE_XML'), Path(r'$NOMAD_DB'), Path(r'$OUTPUT_XML')); print('Stats:', stats)\""
        ;;
    stats)
        echo "SQLite state stats:"
        ssh $NOMAD_USER@$NOMAD_IP "$NOMAD_VENV -c \"import sys; sys.path.insert(0, r'$NOMAD_REPO'); from film_indexer.state.db import State; from pathlib import Path; s = State(Path(r'$NOMAD_DB')); print(s.stats())\""
        ;;
    help|*)
        echo "Film-indexer pipeline launcher"
        echo ""
        echo "Usage:"
        echo "  ./run_pipeline.sh scan              - Phase 0 inventory scan"
        echo "  ./run_pipeline.sh batch [LIMIT] [WORKERS] [BUDGET]  - Phase 3 async batch"
        echo "  ./run_pipeline.sh patch SOURCE [OUTPUT]             - Phase 4 FCPXML patch"
        echo "  ./run_pipeline.sh stats             - SQLite state stats"
        echo ""
        echo "Examples:"
        echo "  ./run_pipeline.sh scan"
        echo "  ./run_pipeline.sh batch 20 6 30.0"
        echo "  ./run_pipeline.sh patch /Users/me/goldberg.fcpxml"
        ;;
esac
