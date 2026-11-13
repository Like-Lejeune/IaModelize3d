import { useCallback, useEffect, useRef, useState } from "react";

/** Loads `load()` once, then again every `everyMs` while `keepGoing(data)` holds; `reload` refreshes at once. */
export function usePolled<T>(load: () => Promise<T>, everyMs: number, keepGoing: (data: T) => boolean = () => true) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const loadRef = useRef(load);
  const goRef = useRef(keepGoing);
  loadRef.current = load;
  goRef.current = keepGoing;

  const reload = useCallback(async () => {
    try {
      const d = await loadRef.current();
      setData(d);
      setError(null);
      return d;
    } catch (e) {
      setError(e as Error);
      return null;
    }
  }, []);

  useEffect(() => {
    let alive = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const tick = async () => {
      const d = await reload();
      if (alive && (d === null || goRef.current(d))) timer = setTimeout(tick, everyMs);
    };
    tick();
    return () => {
      alive = false;
      if (timer) clearTimeout(timer);
    };
  }, [reload, everyMs]);

  return { data, error, reload, setData };
}
