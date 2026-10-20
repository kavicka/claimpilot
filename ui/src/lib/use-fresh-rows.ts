"use client";

import { useState } from "react";

/**
 * Keys of rows that arrived (or changed state) with the latest refresh, so the table can mark them.
 * Empty on the first load: a page that just opened has nothing "new". `keyOf` decides what counts as a
 * change, e.g. `${id}:${status}` also marks a claim that moved into this queue.
 */
export function useFreshRows<R>(data: R[] | undefined, keyOf: (row: R) => string): Set<string> {
  // Previous data in state: React's "adjust state while rendering" pattern.
  const [seen, setSeen] = useState<R[] | undefined>(undefined);
  const [known, setKnown] = useState<Set<string>>(() => new Set());
  const [fresh, setFresh] = useState<Set<string>>(() => new Set());
  if (data && data !== seen) {
    const keys = new Set(data.map(keyOf));
    setFresh(seen ? new Set([...keys].filter((k) => !known.has(k))) : new Set());
    setKnown(keys);
    setSeen(data);
  }
  return fresh;
}
