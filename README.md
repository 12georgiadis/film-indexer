# Film Indexer

> Multi-perspective AI editorial council for documentary rushes — Walter Murch + Kirk Baxter + Niels Pagh Andersen via Gemini, with FCPXML keyword injection.

Pipeline d'indexation sémantique de rushes documentaire qui fait passer chaque clip par plusieurs voix éditoriales LLM (Murch, Baxter, Pagh Andersen) et injecte les verdicts dans Final Cut Pro 12 via FCPXML keyword ranges + markers + custom metadata.

**Statut :** PoC en cours — single-clip end-to-end validation.

## Architecture

```
Phase 0 — Inventaire        (scan + hash xxh128 + dedup, SQLite)
Phase 1 — Pre-processing    (BRAW → proxy 720p NVENC, scene detect, audio extract)
Phase 2 — Triage local      (SigLIP 2 + audio fingerprint, élimine 20-30% morts)
Phase 3 — Council Gemini    (Pass A factuel + Pass B Murch/Baxter/Pagh + ethics)
Phase 4 — FCPXML patching   (pattern Lumberyard, keyword ranges + markers)
```

## Council multi-rounds

| Round | Voix | Rôle |
|-------|------|------|
| R1 | Pass A factuel (Gemini) | Visual search, transcript, observations |
| R2 | **Walter Murch** | Verdict éditorial, règle des 6, moment d'or, son qui sauve |
| R3 | **Kirk Baxter** | Réaction vs action, tempo Fincher, blink proxies, J/L cuts |
| R4 | **Niels Pagh Andersen** | Structure documentaire, position dans l'arc, perpétrateur-sujet |
| R5 | Synthèse FCP | Fiche 3 lignes injectable dans FCP 12 |
| R6 (cond.) | **Janet Malcolm** | Council éthique sur clips sensibles uniquement |

## Stack

- **API Gemini** : `google-genai==1.66.0`
- **Modèles** : `gemini-3.1-flash-lite-preview` (Pass A vidéo), `gemini-3.1-pro-preview` (Pass B reasoning)
- **Transcode** : ffmpeg + NVENC RTX 5090 + AMF iGPU AMD bonus
- **FCPXML** : `fcpxml-mcp-server` (DareDev256) + `lxml` + `xmllint` validation
- **Storage** : SQLite WAL + Parquet exports
- **Orchestration** : Python 3.11 + asyncio + tenacity

## Hardware cible

- **Nomad PC** : AMD Ryzen 9 9900X (12C/24T), RTX 5090, iGPU AMD Radeon, 96 GB RAM, 8 TB NVMe
- **Mac** : MacBook Air M3 / Mac Mini M4 — uniquement pour FCP 12 import final

## Statut PoC

Voir `poc_single_clip.py` — pipeline bout-en-bout sur 1 clip BRAW pour validation visuelle dans FCP 12.

## License

MIT (skill réutilisable)
