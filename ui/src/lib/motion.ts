/** How long a "done" check stays on a button before the dialog or form moves on. */
export const DONE_MS = 450;

export function reducedMotion(): boolean {
  return typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
}
