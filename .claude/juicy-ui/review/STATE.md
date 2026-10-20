# State: review

Done (phase 7). Owner chose medium and all groups (A–D). Implemented CSS-only: tokens and cue keyframes in
`packages/claimpilot-ui/src/styles.css`, `useReplay` / `useSwapDirection` in `motion.ts`, `Reveal` in
`Feedback.tsx`; `Button done`, tab count tick and late-flag pop, `DataTable isNew`, row press, Crumbs copy
pop. Review app: action dialog (done check, shake, reveal), claim header (status pop, payout tick/flash,
Approve pulse after reassess, banners via Reveal), panel swap (claim + invoice), document swap, field row
(saved flash/tick, Corrected pop, edit rise, refusal shake, pencil nudge), fresh queue rows (claims +
invoices), login (shake, reveal, done). Verified: package tests 49, app typecheck/lint, e2e 17/17 with cue
assertions. Note: while the dialog shows its check, two "Approve" buttons exist; Playwright's strict-mode
retry starves page timers, so the approve e2e waits for the dialog to close first.
Next option: upload dropzone drag-over state.
