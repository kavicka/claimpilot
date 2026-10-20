# Juice plan: ClaimPilot review app + @claimpilot/ui

Profile: snappy / productive s malými potvrdeniami · Recommended intensity: **medium** · Preview: `playground.html`

## Summary

Základné stavy (hover, press, focus, disabled, otváranie/zatváranie overlayov) už dizajn systém má a sú
dobré. Chýba odozva tam, kde sa **mení obsah alebo dáta**: prepnutie panela či dokumentu, uloženie
opravy, nový stav po rozhodnutí, nové claimy pri pollingu. Najväčší prínos: likvidátor vždy vidí, čo sa
práve zmenilo a že jeho akcia prešla, priamo na mieste, nie len v toaste v rohu.

## A. Chýbajúca odozva

| # | Element | Trigger | Motion | Communicates | Level | Effort |
|---|---|---|---|---|---|---|
| A1 | Tlačidlo (Button) | async akcia skončí | spinner → fajka pop (`pop-from`→1, `dur-2`, emph), label krátko „Hotovo“, šírka sa nemení | „prešlo to“ | M | S |
| A2 | Riadok poľa po uložení opravy | save OK | hodnota tick (`nudge`, `dur-1`), riadok zelený nádych → doznie (`dur-flash`), tag „Corrected“ pop | „uložené tu, v tomto riadku“ | L | S |
| A3 | Inline edit poľa | otvorenie / chyba servera | input sa rozbalí z hodnoty (opacity + `nudge`), pri odmietnutí input 2× trasenie ±3 px (`dur-3`) + chyba sa rozbalí | „edituješ“ / „toto server odmietol“ | M | S |
| A4 | Kopírovať referenciu | klik | ikona copy → fajka pop, tooltip „Skopírované“, po 1,2 s späť | „je v schránke“ | L | S |
| A5 | Riadok tabuľky / poľa | stlačenie | pozadie stmavne o stupeň (`surface-tabs`) na `:active` | „klik zaregistrovaný“ (navigácia trvá chvíľu) | L | S |

## B. Objavenie / zmiznutie

| # | Element | Trigger | Motion | Communicates | Level | Effort |
|---|---|---|---|---|---|---|
| B1 | Obsah panela claimu (Fields/Routing/…) | prepnutie tabu | crossfade + posun `shift` v smere tabu (vpravo → zľava, vľavo → sprava), `dur-3` | „prešiel si na ďalší panel“ | M | S |
| B2 | Stránky dokumentu | prepnutie dokumentu | fade + rise `dur-3`, smer podľa poradia dokumentov; samotný obsah dokumentu sa nemení (žiadny zoom) | „iný dokument“ | L | S |
| B3 | Alerty pod hlavičkou | stav zmizne (pipeline dobehla, reload ok) | zbalenie `grid-rows 1fr→0fr` + fade, `dur-2` exit | „vyriešené“ bez skoku layoutu | L | M |
| B4 | Flag a počet na tabe | flag sa objaví / zmizne | pop in / pop out (`pop-from`, emph) | „pribudlo niečo na kontrolu“ | M | S |
| B5 | Ceruzka na riadku poľa (hover) | hover | k opacity pridať posun 2 px zľava | „dá sa upraviť“ | L | S |

## C. Zmeny hodnôt a stavov

| # | Element | Trigger | Motion | Communicates | Level | Effort |
|---|---|---|---|---|---|---|
| C1 | Počty na taboch fronty | poll zmení číslo | tick (`nudge` zhora, `dur-1`) | „počet sa zmenil“ | M | S |
| C2 | Nový / zmenený riadok vo fronte | poll prinesie nový claim | riadok `accent-soft` nádych → doznie (`dur-flash`) | „toto je nové“ | M | M |
| C3 | Status tag v hlavičke | zmena stavu (akcia, poll) | starý tag fade-out, nový pop (emph) | „stav sa zmenil na…“ | M | S |
| C4 | Payout / suma | reassess zmení číslo | tick + krátky farebný nádych (zelená ak hore, neutrálna ak dole) | „suma sa prepočítala“ | M | S |
| C5 | Approve po reassess | tlačidlo sa odomkne | jeden mäkký pulz prstenca (`accent-track`, 600 ms), raz | „teraz môžeš schváliť“ | M | S |

## D. Delight

| # | Element | Trigger | Motion | Communicates | Level | Effort |
|---|---|---|---|---|---|---|
| D1 | Schválenie claimu | Approve v dialógu prejde | tlačidlo A1 → dialóg odíde → status tag C3 → rozhodovacie tlačidlá prejdú do disabled postupne (stagger 30 ms) → toast | „rozhodnuté, claim odchádza“ | M | M |
| D2 | Login | zlé heslo / úspech | zlé: formulár 2× trasenie ±4 px; úspech: tlačidlo A1 a plynulý prechod na frontu | „skús znova“ / „si dnu“ | M | S |

## Shared changes (affect other pages)

- `packages/claimpilot-ui/src/styles.css` — nové tokeny + keyframes (`cp-tick`, `cp-flash`, `cp-shake`,
  `cp-pulse`, `cp-pop-out`, `cp-swap-*`), všetko pod jedným reduced-motion blokom.
- `packages/claimpilot-ui/src/motion.ts` — `useTick`, `useFlash`, `Reveal` (nové).
- `Button` (prop `done`), `Crumbs` (copy fajka), `Tabs` (flag/count presence, tick), `Tag` (nič, swap
  rieši volajúci cez `Tick`), `Alert` (exit cez `Reveal`).
- Používa ich len `ui/` (review app) a šablóny v `crm-ui` skille; zmeny sa dostanú aj tam cez sync.

## Not proposed (and why)

- Hover lift / zoom na riadkoch a kartách: hustá tabuľka, pohyb by rušil čítanie.
- Animácia samotného dokumentu (zoom, parallax): je to obsah, ktorý sa číta a porovnáva.
- Scroll reveals, first-paint sekvencie: likvidátor otvára stránky stokrát denne, nesmie čakať.
- Zvuky, haptika, konfety.
- Animovaný zoom stránok dokumentu (šírka): spôsobí relayout pri každom kroku; zmena je okamžitá zámerne.

## Open questions

- Intenzita (odporúčam medium = dnešné tempo dizajn systému).
- Ktoré skupiny implementovať.
