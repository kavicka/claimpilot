# Audit: ClaimPilot review app (queue, claim detail, invoice detail)

Skóre: 0 = žiadna odozva, 1 = len skok/zmena bez prechodu, 2 = prechod, ale nehovorí čo sa stalo,
3 = jasná odozva. Before = 2026-10-20 (`__juicy.audit()` na detaile claimu: 131 prvkov, hover chýba 8,
focus-visible pravidlo chýba 30 (väčšinou spoliehajú na globálny `:focus-visible` outline, ok),
reduced motion pokryté).

| Element | hover | focus | press | disabled | loading | success/zmena | appear | disappear | before | after |
|---|---|---|---|---|---|---|---|---|---|---|
| Button (secondary/primary/approve/danger) | 3 | 3 | 3 | 2 (tooltip s dôvodom) | 2 (spinner) | 0 (žiadne „hotovo“) | — | — | 2 | 3 |
| IconButton | 3 | 3 | 3 | 2 | — | — | — | — | 3 | 3 |
| Copy reference (Crumbs) | 3 | 3 | 3 | — | — | 1 (ikona sa vymení bez animácie) | — | — | 2 | 3 |
| Tabs (fronta, panel claimu) | 3 | 3 | — | — | — | 3 (thumb sa posúva) | — | — | 3 | 3 |
| Tab count / flag | — | — | — | — | — | 1 (číslo skočí pri polle) | 1 (flag sa objaví) | 1 | 1 | 3 |
| Obsah panela po prepnutí tabu | — | — | — | — | — | 1 (okamžitý swap) | — | — | 1 | 3 |
| Dokument (prepnutie, stránky) | 3 | 3 | — | — | — | 1 (okamžitý swap) | — | — | 1 | 3 |
| Riadok tabuľky (fronta) | 3 | 3 | 0 | 2 (dim) | — | 1 (nový/zmenený riadok bez signálu) | 3 (rise + stagger) | 1 | 2 | 3 |
| Riadok poľa (field panel) | 3 | 3 | 0 | — | 2 (spinner v ikone) | 1 (hodnota sa vymení, toast) | — | — | 2 | 3 |
| Inline edit poľa | 2 | 3 | — | — | 2 | 1 | 1 (input skočí) | 1 | 1 | 3 |
| Chyba pri uložení poľa | — | — | — | — | — | 2 (rise-in) | 2 | 1 | 2 | 3 |
| Status tag v hlavičke | — | — | — | — | — | 1 (vymení sa) | — | — | 1 | 3 |
| Payout / suma | — | — | — | — | — | 1 (vymení sa) | — | — | 1 | 3 |
| Approve po reassess | — | — | — | 2 | — | 1 (len sa odomkne) | — | — | 1 | 3 |
| Alert (pipeline beží, reload failed) | — | — | — | — | — | — | 3 (rise-in) | 1 (zmizne skokom) | 2 | 3 |
| Dialog akcie | — | 3 | — | — | 2 | 1 (zatvorí sa, toast) | 3 | 3 | 2 | 3 |
| Toast | — | — | — | — | — | — | 3 | 3 | 3 | 3 |
| Checkbox / Switch | 3 | 3 | 3 | — | — | 3 (pop fajky) | — | — | 3 | 3 |
| Login formulár | 3 | 3 | 3 | — | 2 | — | — | — | 2 | 3 |
| Upload dropzone | 2 | 3 | — | — | 2 | 1 | — | — | 2 | 2 |

## Bugs / poznámky

- Prepnutie tabu panela aj dokumentu: obsah sa vymení okamžite, thumb tabu sa pritom posúva 240 ms, takže
  indikátor „dobieha“ obsah, ktorý tam už je.
- Pri pollingu fronty sa počty a riadky menia bez signálu; nový claim nie je vidieť.
- Po uložení opravy poľa je jediná odozva toast vpravo dole, ďaleko od riadku, ktorý sa zmenil.
- Alerty pod hlavičkou miznú skokom a posunú celý layout naraz.

## After (2026-10-20)

Probed with `__juicy.probe()` in the review app and asserted in e2e (`data-flash`, `data-pop`, `data-shake`):
panel swap `cp-swap-next/prev` 240 ms, document `cp-swap-up` 240 ms, copy check `cp-pop-in` 180 ms, saved field
`cp-flash` 900 ms + value tick 180 ms + Corrected pop, refusal shake 240 ms, new queue rows tint 900 ms after
the 240 ms rise. First paint plays no cue (checked: only the existing rise-in). Reduced motion: all new cues
use `--cp-dur-*` / `--cp-nudge` / `--cp-shift` / `--cp-pop-from`, which the reduced-motion block zeroes; the
dialog's "done" pause is skipped. Left at 2: upload dropzone (not in the plan).
