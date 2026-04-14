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
    model_config = ConfigDict(extra="forbid")
    timecode: str  # MM:SS.cc
    duree_utile_sec: float
    nature: Literal["regard", "souffle", "micro-geste", "bascule-emotion", "silence", "parole-vraie", "accident", "aucun"]
    raison: str  # 25 mots max


class CriteresMurch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    emotion: int = Field(ge=0, le=10)
    histoire: int = Field(ge=0, le=10)
    rythme: int = Field(ge=0, le=10)
    regard: int = Field(ge=0, le=10)
    plan_2d: int = Field(ge=0, le=10)
    espace_3d: int = Field(ge=0, le=10)
    score_total: float


class AnalyseSon(BaseModel):
    model_config = ConfigDict(extra="forbid")
    verdict_son: Literal["PORTE_LE_PLAN", "SOUTIENT", "NEUTRE", "TRAHIT"]
    texture: str
    silence_utile: bool
    le_son_sauve_l_image: bool
    worldizing_naturel: Optional[str] = None


class ConseilEditorial(BaseModel):
    model_config = ConfigDict(extra="forbid")
    usage_recommande: Literal["ouverture", "transition", "climax", "respiration", "b_roll_textuel", "a_eviter"]
    position_dans_sequence: Literal["tete", "corps", "queue", "isole"]
    couper_a: str  # MM:SS.cc
    ne_pas_depasser: str  # MM:SS.cc
    danger: Optional[str] = None  # 'Joshua se regarde performer ici'


class RaccordsContinuite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    regard_entrant: Literal["gauche", "droite", "camera", "absent"]
    regard_sortant: Literal["gauche", "droite", "camera", "absent"]
    mouvement_entrant: Optional[str] = None
    mouvement_sortant: Optional[str] = None
    blink_naturel_a: Optional[str] = None  # MM:SS.cc


class Murch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: str = SCHEMA_VERSION
    clip_hash: str

    statut_prise: Literal["EXCEPTIONNELLE", "BONNE", "PASSABLE", "MAUVAISE"]
    justification_verdict: str  # 20 mots max

    moment_cle: MomentCle
    emotion_dominante_primaire: str  # 1 mot concret (vergogne, defi, vide, jubilation-froide)
    emotion_temperature: Literal["froide", "tiede", "brulante"]
    emotion_ambivalence: Optional[str] = None

    criteres_murch: CriteresMurch
    analyse_son: AnalyseSon
    conseil_editorial: ConseilEditorial
    raccords_continuite: RaccordsContinuite


# ============================================================
# BAXTER — MÉCANIQUE DU CUT
# ============================================================


class ReactionVsAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["ACTION", "REACTION", "LES_DEUX", "INDETERMINE"]
    valeur_reaction: Optional[str] = None
    intensite: int = Field(ge=1, le=5)


class BlinkAnalysis(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cut_points_estimes: list[str] = Field(default_factory=list)  # ranges "00:14.20-00:14.80"
    confiance: Literal["HAUTE", "MOYENNE", "BASSE"]
    proxy_utilise: Optional[Literal["blink", "relachement_musculaire", "fin_expiration", "regard_eteint", "deglutition"]] = None


class TempoFincher(BaseModel):
    model_config = ConfigDict(extra="forbid")
    registre: Literal["ZEN_CONTROLE", "CHAOS_PERTE_CONTROLE", "TRANSITION"]
    jump_cut_eligible: bool
    etirement_possible_sec: float


class SonRenKlyce(BaseModel):
    model_config = ConfigDict(extra="forbid")
    texture: str
    j_cut_potential: Literal["HAUT", "MOYEN", "NUL"]
    l_cut_potential: Literal["HAUT", "MOYEN", "NUL"]
    ancrage_sonore: Optional[str] = None  # MM:SS.cc


class PoidsTemporel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    duree_ideale_sec: float
    risk_too_long: str
    risk_too_short: str


class Baxter(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: str = SCHEMA_VERSION
    clip_hash: str

    reaction_vs_action: ReactionVsAction
    blink_analysis: BlinkAnalysis
    tempo_fincher: TempoFincher
    son_ren_klyce: SonRenKlyce
    poids_temporel: PoidsTemporel
    verdict_baxter: str  # UNE phrase tranchante


# ============================================================
# PAGH ANDERSEN — STRUCTURE NARRATIVE
# ============================================================


class PaghAndersen(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: str = SCHEMA_VERSION
    clip_hash: str

    apport_arc_joshua: str  # 1 phrase : ce que ce plan ajoute
    apport_type: Literal["nouveau_pli", "confirme_pli", "contredit", "ouvre_porte_persona", "cul_de_sac"]

    acte_film: Literal["acte_1_jacksonville_present", "acte_2_persona_factory", "acte_3_australi_witness_arrestation", "acte_4_prison", "acte_5_present_qui_parle", "transverse"]

    fonction_structurelle: Literal["PILIER", "LIEN"]

    plan_frere_appele: str  # 1 phrase : ce qui doit précéder ou suivre

    performance_score: int = Field(ge=0, le=100)  # 0 = vrai Joshua, 100 = pure performance
    drop_moment_timecode: Optional[str] = None  # le moment où Joshua sort de sa fiction
    drop_moment_description: Optional[str] = None

    note_pagh: str  # 1 phrase finale lisible à 3h du matin


# ============================================================
# JANET MALCOLM — COUNCIL ÉTHIQUE CONDITIONNEL
# ============================================================


class JanetMalcolm(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: str = SCHEMA_VERSION
    clip_hash: str

    qui_parle: str  # 1 phrase : Joshua volontaire / inconscient / persona / etc.
    qui_est_blesse: list[str]  # liste des entités blessées potentielles

    source_autorise_usage: bool
    verbatim_required: bool  # True si source PACER/Corrlinks
    verbatim_source: Optional[Literal["PACER_100_7", "PACER_100_8", "PACER_89_1", "PACER_89_2", "CORRLINKS", "OTHER"]] = None

    rend_violence_consommable: bool

    target_present: bool
    targets: list[str] = Field(default_factory=list)  # list of target tags

    verdict: Literal["USABLE", "CONDITIONAL", "UNUSABLE"]
    conditions: list[str] = Field(default_factory=list)  # floutage, voix-off recontextualisée, carton, non-usage

    note_finale_malcolm: str  # 1 phrase pour Ismaël à 3h du matin


# ============================================================
# SYNTHESE FCP — fiche finale 3 lignes
# ============================================================


class SyntheseFCP(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: str = SCHEMA_VERSION
    clip_hash: str

    fcp_note_3_lines: str
    keywords: list[str]  # ["#or", "#joshua-bascule", "#performance:tanya_cohen", "#verbatim"]
    priority_1_5: int = Field(ge=1, le=5)
    edit_intent: Literal["A_ROLL", "B_ROLL", "REJECT", "DEEP_REVIEW"]
    link_to_full_council: Optional[str] = None  # path vers JSON complet


# ============================================================
# CLIP ANALYSIS — consolidation finale
# ============================================================


class ClipAnalysis(BaseModel):
    """Consolide les 4-5 passes éditoriales d'un clip."""
    model_config = ConfigDict(extra="forbid")
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
