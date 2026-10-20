# Motion profile: ClaimPilot (@claimpilot/ui + review app)

Updated: 2026-10-20 · Intensity: **medium** · Prefix: `cp`

## Personality

**Snappy / productive s malými potvrdeniami.** Interný nástroj pre likvidátorov: hustý, tabuľkový,
formálny jazyk, svetlá téma, malé rádiusy. Pohyb má potvrdzovať akcie a ukazovať, čo sa zmenilo, nie
baviť. Krátke dráhy (2–6 px), žiadne dlhé fade, prekmit (`--cp-ease-emph`) len na potvrdzujúcich
objektoch (fajka, odznak, flag, nový stav). Dizajn systém už tento jazyk má; rozširujeme ho, nemeníme.

## Brand signals

| Signal | Evidence (where) | Leans |
|---|---|---|
| Palette | biela, `surface-tabs` #f4f3f3, jeden akcent #2277ce, stavové tóny | calm/snappy |
| Type | Plus Jakarta Sans 11–12 px, Inter, tabular figures | productive |
| Radius | 6–12 px, hairline strokes | snappy |
| Density | tabuľky 36 px riadky, 2-stĺpcový review layout | snappy (krátke dráhy) |
| Copy tone | formálny, vecný, bez výkričníkov | calm |
| Audience | likvidátori, celý deň v nástroji | snappy (nič ich nesmie zdržiavať) |
| Existing motion | 120/180/240 ms, `cubic-bezier(.4,0,.2,1)`, emph `(.34,1.4,.64,1)`, press .97, rise 6 px, slide 16 px, rows stagger 20 ms | snappy + confirmations |

## Tokens

| Token | lite | medium | full | Role |
|---|---|---|---|---|
| `--cp-dur-1` | 100ms | 120ms | 140ms | stav (farba, hover, press) |
| `--cp-dur-2` | 140ms | 180ms | 220ms | enter/exit malých prvkov |
| `--cp-dur-3` | 200ms | 240ms | 300ms | panely, indikátory, swap obsahu |
| `--cp-dur-flash` (nové) | 600ms | 900ms | 1200ms | doznievanie zvýraznenia (uložené pole, nový riadok) |
| `--cp-ease` | (.4,0,.2,1) | (.4,0,.2,1) | (.22,1,.36,1) | štandard |
| `--cp-ease-emph` | = ease | (.34,1.4,.64,1) | (.34,1.56,.64,1) | potvrdenia |
| `--cp-ease-exit` | (.4,0,1,1) | (.4,0,1,1) | (.4,0,1,1) | odchody |
| `--cp-nudge` (nové) | 1px | 2px | 3px | tick hodnoty, posun ikony |
| `--cp-rise` | 3px | 6px | 9px | enter zdola |
| `--cp-shift` (nové) | 4px | 8px | 14px | swap panelu v smere tabu |
| `--cp-press` | 1 | 0.97 | 0.95 | stlačenie |
| `--cp-pop-from` (nové) | 0.85 | 0.6 | 0.4 | pop odznaku/fajky |

Existujúce hodnoty ostávajú (medium = dnešný stav). Nové tokeny len dopĺňajú chýbajúce role.

## Vocabulary (where it lives)

| Piece | Path | Use for |
|---|---|---|
| tokens + keyframes | `packages/claimpilot-ui/src/styles.css` (motion block) | všetko |
| `usePresence`, `useThumb`, `useInert` | `packages/claimpilot-ui/src/motion.ts` (existujú) | overlays, taby |
| `useReplay` + `data-tick/flash/shake/pop/pulse` | `packages/claimpilot-ui/src/motion.ts`, `styles.css` | zmenené čísla, stavy, odmietnutia |
| `Reveal` | `packages/claimpilot-ui/src/components/Feedback.tsx` | alerty a bloky, čo prichádzajú/odchádzajú |
| `useSwapDirection` | `packages/claimpilot-ui/src/motion.ts` | obsah vymenený tabom / dokumentom |

## Decisions

- 2026-10-20 — CSS only, bez knižnice (projekt žiadnu nemá).
- 2026-10-20 — Owner: medium, všetky skupiny A–D. Cues cez `useReplay` + data atribúty (a/b páry keyframes),
  nič sa nehrá pri prvom načítaní.
