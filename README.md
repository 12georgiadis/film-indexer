# film-indexer

> **Multi-perspective AI editorial council for documentary rushes** — Walter Murch + Kirk Baxter + Niels Pagh Andersen via Gemini, with FCPXML keyword injection for Final Cut Pro 12.

Pipeline d'indexation sémantique de rushes documentaire qui fait passer chaque clip par plusieurs voix éditoriales LLM (Murch, Baxter, Pagh Andersen) et injecte les verdicts dans Final Cut Pro 12 via FCPXML keyword ranges + markers + custom metadata.

**Status:** Beta / PoC validé bout-en-bout.

> **2026 update — SpliceKit complement**: film-indexer generates FCPXML keyword ranges that you import into FCP manually. For real-time injection without the XML roundtrip, pair it with [SpliceKit MCP](https://github.com/elliotttate/SpliceKit) — a Claude Code MCP that controls FCP directly in-process. film-indexer handles the indexing and analysis; SpliceKit handles the live timeline writes.

---

## Why this exists

Aucun outil sur le marché ne combine :
- Analyse multi-LLM avec perspectives éditoriales humaines (Murch + Baxter + Pagh Andersen)
- FCPXML 1.13 keyword ranges + markers timecodés injection
- Batch scaling >1000 clips pour documentaire long format
- Tuning projet-spécifique avec garde-fous éthiques
- Hybride local (GPU) + cloud (Gemini) pour maîtriser les coûts

Les alternatives existantes :
| Outil | Limite |
|-------|--------|
| **Jumper** (Witchcraft) | Search local seulement, pas de génération keywords FCPXML batch |
| **Strada** (Cioni) | 100% cloud lock-in, pas customisable |
| **FCP Video Tag** (Ulti.Media) | Mono-modèle, pas de markers timecodés |
| **Lumberjack backLogger** | Audio/transcript only, humain dans la boucle |
| **Eddie AI** | Boîte noire, orienté cuts pas indexation |
| **FCP 12 Visual Search natif** | Lent (0.2x RT), US English only, pas exportable FCPXML |

**film-indexer** est inédit sur l'angle "multi-perspective editorial council appliqué aux rushes documentaire".

---

## Architecture

```
Phase 0 — Inventaire        Scan multi-drives + hash xxh128 + SQLite state
Phase 1 — Pre-processing    BRAW → proxy 720p (DaVinci), ffmpeg NVENC, audio extract
Phase 2 — Triage local      SigLIP 2 + audio fingerprint (gratuit RTX 5090)
Phase 3 — Council Gemini    5 voix (Pass A + Murch + Baxter + Pagh + Synthese)
                            + Janet Malcolm ethics conditionnel
Phase 4 — FCPXML patch      Lumberyard pattern, patch FCPXML existant de FCP 12
```

## Stack

- **Python** 3.11 + asyncio pour vrai parallélisme
- **Gemini API** via `google-genai==1.66.0` (PAS l'ancien deprecated `google-generativeai`)
- **Modèles** : `gemini-2.5-flash` (Pass A vidéo safe) + `gemini-3-flash-preview` (Pass B reasoning)
- **Storage** : SQLite WAL avec idempotency via composite keys
- **Transcode** : ffmpeg + NVENC (Nvidia GPU 9e gen)
- **FCPXML** : lxml + xmllint validation + rational timecodes
- **Hardware recommandé** : PC Windows + RTX 5090 + 96 GB RAM + NVMe interne

## Installation

```bash
git clone https://github.com/12georgiadis/film-indexer.git
cd film-indexer
python -m venv .venv
source .venv/bin/activate   # Linux/Mac
# OR
.venv\Scripts\activate      # Windows
pip install -r requirements.txt

export GEMINI_API_KEY="your-key"
```

## Usage

### PoC single clip

```bash
python -m film_indexer.poc_single_clip \
  --src /path/to/clip.mov \
  --out /path/to/output
```

Génère : `<hash>_FINAL.json` (analyse consolidée) + `<hash>.fcpxml` (à importer dans FCP 12).

### Batch run (recommended)

```bash
# Phase 0 : scanner les drives
python -m film_indexer.scan_drives \
  --roots /drive1 /drive2 \
  --since 2026-02-18 \
  --db state.db

# Phase 3 : batch council Gemini (recommended path, stable)
python -m film_indexer.batch_run \
  --db state.db \
  --out /path/to/output \
  --limit 100 \
  --workers 4 \
  --budget-cap 30.0
```

> **Note :** `async_pipeline.py` existe mais a un bug Pass B (asyncio.gather silencieux).
> Utiliser `batch_run.py` pour la production. Le vrai async sera réglé dans une prochaine version.

### FCPXML patcher (Lumberyard pattern)

```bash
# 1. Dans FCP 12 : File → Export XML → my_library.fcpxml
# 2. Patch le FCPXML avec les analyses
python -m film_indexer.lib.fcpxml_patcher \
  source=my_library.fcpxml \
  state_db=state.db \
  output=my_library_indexed.fcpxml

# 3. Valider
xmllint --noout my_library_indexed.fcpxml

# 4. Dans FCP 12 : File → Import XML → réimport avec keywords + markers
```

## Council multi-rounds

| Round | Voix | Rôle | Coût moyen/clip |
|-------|------|------|-----------------|
| R1 | Pass A factuel (Gemini Flash) | Visual search + transcript + observations | $0.005 |
| R2 | **Walter Murch** | Verdict éditorial, règle des 6, moment d'or | $0.004 |
| R3 | **Kirk Baxter** | Réaction vs action, tempo Fincher, blink proxies | $0.004 |
| R4 | **Niels Pagh Andersen** | Structure narrative, perpétrateur-sujet | $0.004 |
| R5 | Synthèse FCP | Fiche 3 lignes + keywords + intent | $0.002 |
| R6 | Janet Malcolm (conditionnel) | Éthique sur matériel sensible | $0.005 |

**Total moyen : ~$0.02 par clip.**

## Project tuning

Pour adapter à un autre film, créer un repo privé `<film>-rushes-index` avec :

```
<film>-rushes-index/
├── film.toml              # config projet (chemins, budget, modèles)
├── prompts/
│   ├── goldberg_context.md    # contexte projet 300 mots
│   ├── murch_<film>.md        # surcharge Murch
│   └── baxter_<film>.md       # surcharge Baxter
├── subjects/                  # taxonomie personnes/personas
├── themes/                    # thèmes narratifs
└── risks/                     # règles dures éthiques
```

Voir [goldberg-rushes-index](https://github.com/12georgiadis/goldberg-rushes-index) (privé) pour un exemple complet.

## Coûts réels mesurés

Sur 16 clips MOV Floride test (durée 1s-2min, proxies H265) :

| Métrique | Valeur |
|----------|--------|
| Total dépensé | $0.637 |
| Moyen par clip | $0.026 |
| Pipeline 5 voix (Murch + Baxter + Pagh + Malcolm conditionnel + Synthèse) | ✓ |
| FCPXML valide xmllint | ✓ |

Projection **1024 clips Goldberg** : ~**$25-50 total**, ~**30 min wall clock** en batch async workers=6.

## License

MIT — Méthode publique, tes matériaux restent privés.

## Credits

- Conçu pour **The Goldberg Variations** (documentaire Ismaël Joffroy Chandoutis, Films Grand Huit)
- Inspirations méthode : Walter Murch (*In the Blink of an Eye*), Kirk Baxter (interviews Fincher/Mindhunter), Niels Pagh Andersen (*The Act of Killing* editor), Janet Malcolm (*The Journalist and the Murderer*)
- Pattern FCPXML patching : Lumberyard (Philip Hodgetts / Intelligent Assistance)
- Hardware de développement : Nomad PC (AMD Ryzen 9 9900X + RTX 5090 + 96 GB)
