"""
Pydantic schemas pour le pipeline film-indexer.

Quatre passes éditoriales :
- PassA : extraction factuelle (visual + audio)
- Murch : verdict éditorial
- Baxter : mécanique du cut
- PaghAndersen : structure narrative documentaire
- JanetMalcolm : council éthique conditionnel
- Synthese : fiche FCP finale
"""
from __future__ import annotations

from typing import Literal, Optional
from pydantic import BaseModel, Field, ConfigDict


SCHEMA_VERSION = "1.0.0"


# ============================================================
# PASS A — EXTRACTION FACTUELLE (structure groupée pour Gemini)
# ============================================================


class PeopleObservation(BaseModel):
    model_config = ConfigDict(extra="ignore")
    count: Optional[str] = None  # null | one_person | two_people | group
    descriptions: list[str] = Field(default_factory=list)
    emotions: list[str] = Field(default_factory=list)


class SceneObservation(BaseModel):
    model_config = ConfigDict(extra="ignore")
    location: Optional[str] = None  # interieur | exterieur
    environment: Optional[str] = None
    time_of_day: Optional[str] = None
    weather: Optional[str] = None


class AestheticObservation(BaseModel):
    model_config = ConfigDict(extra="ignore")
    dominant_colors: Optional[str] = None
    lighting: Optional[str] = None
    mood: Optional[str] = None


class VisualSearch(BaseModel):
    model_config = ConfigDict(extra="ignore")
    objects: list[str] = Field(default_factory=list)
    actions: list[str] = Field(default_factory=list)
    people: PeopleObservation = Field(default_factory=PeopleObservation)
    shot_type: Optional[str] = None
    camera_movement: Optional[str] = None
    scene: SceneObservation = Field(default_factory=SceneObservation)
    aesthetic: AestheticObservation = Field(default_factory=AestheticObservation)


class AudioTranscript(BaseModel):
    model_config = ConfigDict(extra="ignore")
    transcript: str = ""
    language: Optional[str] = None
    speakers: list[str] = Field(default_factory=list)
    speaker_count: int = 0
    dominant_sounds: list[str] = Field(default_factory=list)
    audio_quality: Optional[str] = None  # studio | clean | acceptable | noisy | unusable
    silence_moments_seconds: list[float] = Field(default_factory=list)


class Technique(BaseModel):
    model_config = ConfigDict(extra="ignore")
    duration_s: float = 0.0
    estimated_snr_db: Optional[float] = None
    clipping_detected: bool = False
    focus_quality: Optional[str] = None  # sharp | soft | out_of_focus
    exposure: Optional[str] = None  # underexposed | correct | overexposed | mixed


class ProjectTags(BaseModel):
    model_config = ConfigDict(extra="ignore")
    personas_detected: list[str] = Field(default_factory=list)
    themes_detected: list[str] = Field(default_factory=list)
    targets_detected: list[str] = Field(default_factory=list)
    sensitive_flags: list[str] = Field(default_factory=list)


class PassA(BaseModel):
    """Extraction factuelle d'un clip — structure groupée pour Gemini.

    clip_hash, clip_path, schema_version sont remplis par notre code (pas Gemini).
    """
    model_config = ConfigDict(extra="ignore")
    schema_version: str = SCHEMA_VERSION
    clip_hash: str = ""
    clip_path: str = ""

    visual_search: VisualSearch = Field(default_factory=VisualSearch)
    audio_transcript: AudioTranscript = Field(default_factory=AudioTranscript)
    technique: Technique = Field(default_factory=Technique)
    project_tags: ProjectTags = Field(default_factory=ProjectTags)

    natural_language_queries: list[str] = Field(default_factory=list)


# ============================================================
# MURCH — VERDICT ÉDITORIAL
# ============================================================


class MomentCle(BaseModel):
    """Tolerant to French/English field variants since Gemini improvises."""
    model_config = ConfigDict(extra="allow", populate_by_name=True)
    timecode: Optional[str] = None  # MM:SS.cc
    duree_utile_sec: Optional[float] = Field(default=None, alias="duration_useful_sec")
    nature: Optional[str] = None
    raison: Optional[str] = Field(default=None, alias="reason")


class CriteresMurch(BaseModel):
    model_config = ConfigDict(extra="allow")
    emotion: Optional[int] = Field(default=None, ge=0, le=10)
    histoire: Optional[int] = Field(default=None, ge=0, le=10)
    rythme: Optional[int] = Field(default=None, ge=0, le=10)
    regard: Optional[int] = Field(default=None, ge=0, le=10)
    plan_2d: Optional[int] = Field(default=None, ge=0, le=10)
    espace_3d: Optional[int] = Field(default=None, ge=0, le=10)
    score_total: Optional[float] = None


class AnalyseSon(BaseModel):
    model_config = ConfigDict(extra="allow")
    verdict_son: Optional[str] = None
    texture: Optional[str] = None
    silence_utile: Optional[bool] = None
    le_son_sauve_l_image: Optional[bool] = None
    worldizing_naturel: Optional[str] = None


class ConseilEditorial(BaseModel):
    model_config = ConfigDict(extra="allow")
    usage_recommande: Optional[str] = None
    position_dans_sequence: Optional[str] = None
    couper_a: Optional[str] = None
    ne_pas_depasser: Optional[str] = None
    danger: Optional[str] = None


class RaccordsContinuite(BaseModel):
    model_config = ConfigDict(extra="allow")
    regard_entrant: Optional[str] = None
    regard_sortant: Optional[str] = None
    mouvement_entrant: Optional[str] = None
    mouvement_sortant: Optional[str] = None
    blink_naturel_a: Optional[str] = None


class Murch(BaseModel):
    model_config = ConfigDict(extra="allow")
    schema_version: str = SCHEMA_VERSION
    clip_hash: str = ""

    statut_prise: Optional[str] = None
    justification_verdict: Optional[str] = None

    moment_cle: MomentCle = Field(default_factory=MomentCle)
    emotion_dominante_primaire: Optional[str] = None
    emotion_temperature: Optional[str] = None
    emotion_ambivalence: Optional[str] = None

    criteres_murch: CriteresMurch = Field(default_factory=CriteresMurch)
    analyse_son: AnalyseSon = Field(default_factory=AnalyseSon)
    conseil_editorial: ConseilEditorial = Field(default_factory=ConseilEditorial)
    raccords_continuite: RaccordsContinuite = Field(default_factory=RaccordsContinuite)


# ============================================================
# BAXTER — MÉCANIQUE DU CUT
# ============================================================


class ReactionVsAction(BaseModel):
    model_config = ConfigDict(extra="allow")
    type: Optional[str] = None
    valeur_reaction: Optional[str] = None
    intensite: Optional[int] = Field(default=None, ge=1, le=5)


class BlinkAnalysis(BaseModel):
    model_config = ConfigDict(extra="allow")
    cut_points_estimes: list[str] = Field(default_factory=list)
    confiance: Optional[str] = None
    proxy_utilise: Optional[str] = None


class TempoFincher(BaseModel):
    model_config = ConfigDict(extra="allow")
    registre: Optional[str] = None
    jump_cut_eligible: Optional[bool] = None
    etirement_possible_sec: Optional[float] = None


class SonRenKlyce(BaseModel):
    model_config = ConfigDict(extra="allow")
    texture: Optional[str] = None
    j_cut_potential: Optional[str] = None
    l_cut_potential: Optional[str] = None
    ancrage_sonore: Optional[str] = None


class PoidsTemporel(BaseModel):
    model_config = ConfigDict(extra="allow")
    duree_ideale_sec: Optional[float] = None
    risk_too_long: Optional[str] = None
    risk_too_short: Optional[str] = None


class Baxter(BaseModel):
    model_config = ConfigDict(extra="allow")
    schema_version: str = SCHEMA_VERSION
    clip_hash: str = ""

    reaction_vs_action: ReactionVsAction = Field(default_factory=ReactionVsAction)
    blink_analysis: BlinkAnalysis = Field(default_factory=BlinkAnalysis)
    tempo_fincher: TempoFincher = Field(default_factory=TempoFincher)
    son_ren_klyce: SonRenKlyce = Field(default_factory=SonRenKlyce)
    poids_temporel: PoidsTemporel = Field(default_factory=PoidsTemporel)
    verdict_baxter: Optional[str] = None


# ============================================================
# PAGH ANDERSEN — STRUCTURE NARRATIVE
# ============================================================


class PaghAndersen(BaseModel):
    model_config = ConfigDict(extra="allow")
    schema_version: str = SCHEMA_VERSION
    clip_hash: str = ""

    apport_arc_joshua: Optional[str] = None
    apport_type: Optional[str] = None
    acte_film: Optional[str] = None
    fonction_structurelle: Optional[str] = None
    plan_frere_appele: Optional[str] = None

    performance_score: Optional[int] = Field(default=None, ge=0, le=100)
    drop_moment_timecode: Optional[str] = None
    drop_moment_description: Optional[str] = None

    note_pagh: Optional[str] = None


# ============================================================
# JANET MALCOLM — COUNCIL ÉTHIQUE CONDITIONNEL
# ============================================================


class JanetMalcolm(BaseModel):
    model_config = ConfigDict(extra="allow")
    schema_version: str = SCHEMA_VERSION
    clip_hash: str = ""

    qui_parle: Optional[str] = None
    qui_est_blesse: list[str] = Field(default_factory=list)

    source_autorise_usage: Optional[bool] = None
    verbatim_required: Optional[bool] = None
    verbatim_source: Optional[str] = None

    rend_violence_consommable: Optional[bool] = None

    target_present: Optional[bool] = None
    targets: list[str] = Field(default_factory=list)

    verdict: Optional[str] = None
    conditions: list[str] = Field(default_factory=list)

    note_finale_malcolm: Optional[str] = None


# ============================================================
# SYNTHESE FCP — fiche finale 3 lignes
# ============================================================


class SyntheseFCP(BaseModel):
    model_config = ConfigDict(extra="allow")
    schema_version: str = SCHEMA_VERSION
    clip_hash: str = ""

    fcp_note_3_lines: Optional[str] = None
    keywords: list[str] = Field(default_factory=list)
    priority_1_5: Optional[int] = Field(default=None, ge=1, le=5)
    edit_intent: Optional[str] = None
    link_to_full_council: Optional[str] = None


# ============================================================
# CLIP ANALYSIS — consolidation finale
# ============================================================


class ClipAnalysis(BaseModel):
    """Consolide les 4-5 passes éditoriales d'un clip."""
    model_config = ConfigDict(extra="ignore")
    schema_version: str = SCHEMA_VERSION
    clip_hash: str
    clip_path: str

    pass_a: PassA
    murch: Optional[Murch] = None
    baxter: Optional[Baxter] = None
    pagh_andersen: Optional[PaghAndersen] = None
    janet_malcolm: Optional[JanetMalcolm] = None
    synthese: Optional[SyntheseFCP] = None

    # Cost tracking
    total_cost_usd: float = 0.0
    timings_s: dict = Field(default_factory=dict)
