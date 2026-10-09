"use client";

import { useCallback, useEffect, useEffectEvent, useState } from "react";

import { errorMessage } from "./api";

interface State<T> {
  key: string | null;
  data?: T;
  error?: string;
}

interface Options<T> {
  /** Re-fetch every n ms while the page is open. */
  pollMs?: number;
  /** Skip a poll when this returns false for the current data. */
  pollWhile?: (data: T | undefined) => boolean;
}

/**
 * Fetch on mount and whenever `key` changes. Old data stays on screen during reloads and polls;
 * `loading` is true only until the first answer for the current key arrives.
 */
export function useFetch<T>(key: string | null, fetcher: () => Promise<T>, options: Options<T> = {}) {
  const { pollMs, pollWhile } = options;
  const [state, setState] = useState<State<T>>({ key: null });
  const [tick, setTick] = useState(0);

  const run = useEffectEvent((k: string, cancelled: () => boolean) => {
    fetcher().then(
      (data) => {
        if (!cancelled()) setState({ key: k, data });
      },
      (err: unknown) => {
        if (!cancelled())
          setState((s) => ({
            key: k,
            data: s.key === k ? s.data : undefined,
            error: errorMessage(err),
          }));
      },
    );
  });

  const poll = useEffectEvent((k: string, cancelled: () => boolean) => {
    if (document.hidden) return;
    if (pollWhile && !pollWhile(state.key === k ? state.data : undefined)) return;
    run(k, cancelled);
  });

  useEffect(() => {
    if (key === null) return;
    let cancelled = false;
    const isCancelled = () => cancelled;
    run(key, isCancelled);
    const timer = pollMs ? window.setInterval(() => poll(key, isCancelled), pollMs) : undefined;
    return () => {
      cancelled = true;
      if (timer) window.clearInterval(timer);
    };
  }, [key, tick, pollMs]);

  const reload = useCallback(() => setTick((t) => t + 1), []);
  const mutate = useCallback(
    (fn: (data: T) => T) => setState((s) => (s.data === undefined ? s : { ...s, data: fn(s.data) })),
    [],
  );

  const current = state.key === key;
  return {
    data: current ? state.data : undefined,
    error: current ? state.error : undefined,
    loading: key !== null && !current,
    reload,
    mutate,
  };
}
