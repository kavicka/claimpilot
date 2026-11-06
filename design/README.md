# Design

The review UI is built on `@crm-ui/react`, a design system kept in its own repository. Its tokens
and components were measured from two Figma dashboard templates (tables, tabs, drawer, timeline,
checklist, cards, popover, coachmarks) and rebuilt in React; the source files, screenshots and
image assets are not part of this repository.

Decisions taken during the extraction that still shape the UI:

- One base width of 1440 px; the design system's `scaling.css` grows the UI on wider screens.
- Light theme only.
- Text colours from the templates that were under 4.5:1 were darkened in the tokens to reach WCAG AA.
- Icons come from Hugeicons (outline) and Tabler (filled), not from the template exports.
- Hairline borders are drawn as inset box-shadows (`stroke-*` tokens).
- Status badges are `Tag`s; there is no `Badge` component.
