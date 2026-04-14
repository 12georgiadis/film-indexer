# CONTEXTE PROJET — The Goldberg Variations

> Ce contexte est injecté dans CHAQUE appel Gemini de notre pipeline.
> Sans lui, les voix Murch/Baxter/Pagh/Malcolm parlent dans le vide.

The Goldberg Variations est un documentaire d'auteur d'Ismaël Joffroy Chandoutis sur Joshua Ryne Goldberg, autiste américain de Jacksonville (Floride) qui a opéré 30+ personas en ligne entre 2006 et 2015, dont une (AustraliWitness, djihadiste) lui a valu une arrestation FBI en septembre 2015 et 8 ans de prison fédérale. Production : Films Grand Huit. Résidence : Villa Albertine 2026.

## Joshua Ryne Goldberg — qui filmer

- Filmé SOIR/NUIT uniquement (jamais golden hour). Rebecca, sa mère, décide tout.
- Il flap (mouvement répétitif des mains, marqueur autistique), pace dans la cuisine, parfois chante. **Ces moments sont de l'OR. Flag `gold:autistic_body_marker`, `gold:pacing_kitchen`, `gold:song`.**
- Plans clés à reconnaître : enterrement du chien (Spirit/Luna), pacing cuisine, browsing live (Joshua face écran), pilules placebo salle de bain.
- **Si Rebecca dit "fatigue" → ignorer** (feedback record, pas Joshua qui décroche).

## 12 personas à tagger automatiquement

Tag : `persona:nom_snake_case`. Distinction `performance:` vs `reference:` (jouer vs parler de).

| Tag | Description courte |
|-----|-------------------|
| `persona:moonmetropolis` | Libertarien pro-1er Amendement, masque de base, autiste déclaré |
| `persona:australiwitness` | Djihadiste islamiste australien, `@AusWitness`, lié à l'attentat de Garland (Texas, mai 2015) |
| `persona:tanya_cohen` | Féministe radicale pro-censure, Australienne fictive, Thought Catalog, Amnesty |
| `persona:michael_slay` | Journaliste néo-nazi, Daily Stormer |
| `persona:amina_blackberry` | Femme noire musulmane progressiste, Twitter @AminaBlackberry |
| `persona:emily_americana` | Femme samoane libertarienne, Reddit |
| `persona:wakeupwhiteman` | Suprémaciste blanc Stormfront |
| `persona:dreamerryoko` | Étudiante japonaise libertarienne, Twitter en japonais |
| `persona:madotsuki_the_dreamer` | Cinéphile Yume Nikki, IMDb obscur |
| `persona:metropolisforever` | Fan Tezuka, Criterion |
| `persona:dr_shlomo_goldstein` | Parodie antisémite "oy vey goyim" |
| `persona:mouthful_of_grandpa` | Trolling scatologique pur |

Cibles réelles à tagger : `target:mariam_veiszadeh`, `target:luke_mcmahon`, `target:elise_potaka`, `target:grant_taylor`, `target:glenn_greenwald`, `target:tom_minear`.

## 10 thèmes narratifs

| Tag | Mots-clés Gemini |
|-----|-----------------|
| `theme:logique_autistique` | "literal", "rules", "each space its own rules", flapping, archivage compulsif |
| `theme:persona_factory` | "another character", "modules", "deploy", coexistence persona opposées |
| `theme:free_speech_absolute` | "1st Amendment", "Australians", "freedom of speech" |
| `theme:corps_absent` | chambre, écran seul visage bleu, léthargie physique vs hyperactivité mentale |
| `theme:martyr_terror` | Garland, Boston, Craigslist bomb, mujahideen |
| `theme:prison_corps` | CD prison 2016-2024, Corrlinks, Butner, "I don't take pleasure in anything" |
| `theme:variations_bach` | Goldberg Variations, aria, canon, motif récurrent |
| `theme:performance_sincerite` | "the joke is there is no joke", trolling devenu sincère |
| `theme:influence_distance` | doxing, "from my bedroom", unmoved mover |
| `theme:archivage_brain_rot` | Wikipedia 5000 entries, YouTube Poop, Sora 2 slop |

## ⚠️ Zones de risque (règles dures)

1. **Sources PACER** (Doc 100-7, 100-8, 89-1, 89-2) → **`verbatim_required`** absolu, **interdiction de paraphraser**.
2. **Joshua a contesté 2 paraphrases inner voice le 11 avril 2026** → toute reformulation auto = risque légal.
3. **Construction de bombe** (Doc 100-8, Christmas lights, filament, Boston) → flag `sensitive:terror_construction`.
4. **Harcèlement Mariam Veiszadeh** → flag `target:mariam_veiszadeh + sensitive:harassment`.
5. **Le rêve de la bombe = roleplay** → JAMAIS présenté comme vécu.
6. **Anachronisme soyjak post-prison** → flag `sensitive:anachronism`.
7. **Redondance** : 35 507 posts + 42 datasets voice cloning → détecter duplication sémantique entre clips.

## Méthode liquid writing — ce que cherche le monteur

Ne cherche pas les beaux plans. Cherche :
- **Coexistences impossibles** (Joshua performe deux personas opposées dans la même minute)
- **Aveux littéraux involontaires** ("I don't take pleasure in anything")
- **Marqueurs corporels autistiques** (flap, pacing, silence long, archivage compulsif live)
- **Match cuts potentiels** sur un mot identique d'une persona à l'autre
- **Le moment où Joshua DROP** (sort de sa fiction, devient un corps)

Règle absolue : **pensée littérale, pas de sous-entendus sociaux, pas de psychologisation, pas de moralisation.**
