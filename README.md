**English** · [Français](README.fr.md)

# film-indexer

> **Multi-perspective AI editorial council for documentary rushes**: Walter Murch + Kirk Baxter + Niels Pagh Andersen via Gemini, with FCPXML keyword injection for Final Cut Pro 12.

A semantic indexing pipeline for documentary rushes that runs every clip through several LLM editorial voices (Murch, Baxter, Pagh Andersen) and injects the verdicts into Final Cut Pro 12 via FCPXML keyword ranges + markers + custom metadata.

<img src="monde.jpg" alt="film-indexer" width="100%">

**Status:** Beta / end-to-end validated PoC.

> **2026 update, SpliceKit complement**: film-indexer generates FCPXML keyword ranges that you import into FCP manually. For real-time injection without the XML roundtrip, pair it with [SpliceKit MCP](https://github.com/elliotttate/SpliceKit), a Claude Code MCP that controls FCP directly in-process. film-indexer handles the indexing and analysis; SpliceKit handles the live timeline writes.

---

## Why this exists

No tool on the market combines:
- Multi-LLM analysis with human editorial perspectives (Murch + Baxter + Pagh Andersen)
- FCPXML 1.13 keyword ranges + timecoded markers injection
- Batch scaling >1000 clips for feature-length documentary
- Project-specific tuning with ethical guardrails
- Hybrid local (GPU) + cloud (Gemini) to control costs

Existing alternatives:
| Tool | Limitation |
|-------|--------|
| **Jumper** (Witchcraft) | Local search only, no batch FCPXML keyword generation |
| **Strada** (Cioni) | 100% cloud lock-in, not customizable |
| **FCP Video Tag** (Ulti.Media) | Single-model, no timecoded markers |
| **Lumberjack backLogger** | Audio/transcript only, human in the loop |
| **Eddie AI** | Black box, cuts-oriented not indexing |
| **FCP 12 native Visual Search** | Slow (0.2x RT), US English only, not exportable to FCPXML |

**film-indexer** is unprecedented on the "multi-perspective editorial council applied to documentary rushes" angle.

---

## Architecture

```
Phase 0 · Inventory         Multi-drive scan + xxh128 hash + SQLite state
Phase 1 · Pre-processing    BRAW → 720p proxy (DaVinci), ffmpeg NVENC, audio extract
Phase 2 · Local triage      SigLIP 2 + audio fingerprint (free on RTX 5090)
Phase 3 · Gemini council    5 voices (Pass A + Murch + Baxter + Pagh + Synthesis)
                            + conditional Janet Malcolm ethics
Phase 4 · FCPXML patch      Lumberyard pattern, patches FCP 12's existing FCPXML
```

## Stack

- **Python** 3.11 + asyncio for real parallelism
- **Gemini API** via `google-genai==1.66.0` (NOT the old deprecated `google-generativeai`)
- **Models**: `gemini-2.5-flash` (Pass A, video-safe) + `gemini-3-flash-preview` (Pass B reasoning)
- **Storage**: SQLite WAL with idempotency via composite keys
- **Transcode**: ffmpeg + NVENC (9th-gen Nvidia GPU)
- **FCPXML**: lxml + xmllint validation + rational timecodes
- **Recommended hardware**: Windows PC + RTX 5090 + 96 GB RAM + internal NVMe

## Installation

```bash
git clone https://github.com/ismael-joffroy-chandoutis/film-indexer.git
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

Generates: `<hash>_FINAL.json` (consolidated analysis) + `<hash>.fcpxml` (to import into FCP 12).

### Batch run (recommended)

```bash
# Phase 0: scan the drives
python -m film_indexer.scan_drives \
  --roots /drive1 /drive2 \
  --since 2026-02-18 \
  --db state.db

# Phase 3: batch Gemini council (recommended path, stable)
python -m film_indexer.batch_run \
  --db state.db \
  --out /path/to/output \
  --limit 100 \
  --workers 4 \
  --budget-cap 30.0
```

> **Note:** `async_pipeline.py` exists but has a Pass B bug (silent `asyncio.gather` failure).
> Use `batch_run.py` for production. Real async will be fixed in a future version.

### FCPXML patcher (Lumberyard pattern)

```bash
# 1. In FCP 12: File → Export XML → my_library.fcpxml
# 2. Patch the FCPXML with the analyses
python -m film_indexer.lib.fcpxml_patcher \
  source=my_library.fcpxml \
  state_db=state.db \
  output=my_library_indexed.fcpxml

# 3. Validate
xmllint --noout my_library_indexed.fcpxml

# 4. In FCP 12: File → Import XML → re-import with keywords + markers
```

## Multi-round council

| Round | Voice | Role | Avg cost/clip |
|-------|------|------|-----------------|
| R1 | Factual Pass A (Gemini Flash) | Visual search + transcript + observations | $0.005 |
| R2 | **Walter Murch** | Editorial verdict, rule of six, golden moment | $0.004 |
| R3 | **Kirk Baxter** | Reaction vs action, Fincher tempo, blink proxies | $0.004 |
| R4 | **Niels Pagh Andersen** | Narrative structure, perpetrator-subject | $0.004 |
| R5 | FCP synthesis | 3-line card + keywords + intent | $0.002 |
| R6 | Janet Malcolm (conditional) | Ethics on sensitive material | $0.005 |

**Average total: ~$0.02 per clip.**

## Project tuning

To adapt to another film, create a private `<film>-rushes-index` repo with:

```
<film>-rushes-index/
├── film.toml              # project config (paths, budget, models)
├── prompts/
│   ├── goldberg_context.md    # 300-word project context
│   ├── murch_<film>.md        # Murch override
│   └── baxter_<film>.md       # Baxter override
├── subjects/                  # people/personas taxonomy
├── themes/                    # narrative themes
└── risks/                     # hard ethical rules
```

See [goldberg-rushes-index](https://github.com/ismael-joffroy-chandoutis/goldberg-rushes-index) (private) for a complete example.

## Measured real-world costs

On 16 test MOV clips from Florida (duration 1s-2min, H265 proxies):

| Metric | Value |
|----------|--------|
| Total spent | $0.637 |
| Average per clip | $0.026 |
| 5-voice pipeline (Murch + Baxter + Pagh + conditional Malcolm + Synthesis) | Validated |
| FCPXML valid via xmllint | Validated |

Projection for **1024 Goldberg clips**: ~**$25-50 total**, ~**30 min wall clock** in batch async workers=6.

## License

[PolyForm Noncommercial 1.0.0](https://polyformproject.org/licenses/noncommercial/1.0.0). Public method, your materials stay private.

## Credits

- Designed for **The Goldberg Variations** (documentary by Ismaël Joffroy Chandoutis, Films Grand Huit)
- Method inspirations: Walter Murch (*In the Blink of an Eye*), Kirk Baxter (Fincher/Mindhunter interviews), Niels Pagh Andersen (*The Act of Killing* editor), Janet Malcolm (*The Journalist and the Murderer*)
- FCPXML patching pattern: Lumberyard (Philip Hodgetts / Intelligent Assistance)
- Development hardware: Nomad PC (AMD Ryzen 9 9900X + RTX 5090 + 96 GB)

By [Ismaël Joffroy Chandoutis](https://ismaeljoffroychandoutis.com).
