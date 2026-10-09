import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";

export const DAY_OPTIONS = [1, 7, 30, 90] as const;
const KEY = "agentshield.days";

function readStored(): number {
  try {
    const v = Number(localStorage.getItem(KEY));
    return (DAY_OPTIONS as readonly number[]).includes(v) ? v : 30;
  } catch {
    return 30;
  }
}

interface Ctx {
  days: number;
  setDays: (d: number) => void;
}
const TimeRangeContext = createContext<Ctx>({ days: 30, setDays: () => undefined });

export function TimeRangeProvider({ children }: { children: ReactNode }) {
  const [days, setDaysState] = useState<number>(readStored);
  const setDays = useCallback((d: number) => {
    setDaysState(d);
    try {
      localStorage.setItem(KEY, String(d));
    } catch {
      /* storage unavailable - keep in memory only */
    }
  }, []);
  const value = useMemo(() => ({ days, setDays }), [days, setDays]);
  return <TimeRangeContext.Provider value={value}>{children}</TimeRangeContext.Provider>;
}

export function useDays(): Ctx {
  return useContext(TimeRangeContext);
}
