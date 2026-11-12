// A slip of paper that confirms what just happened. Polite live region; auto-dismisses; one at a time.
import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";

export type SlipTone = "ink" | "cleared" | "critical";
interface Slip { id: number; title: string; body?: string; tone: SlipTone }

const Ctx = createContext<(title: string, body?: string, tone?: SlipTone) => void>(() => {});

export function SlipProvider({ children }: { children: ReactNode }) {
  const [slip, setSlip] = useState<Slip | null>(null);
  const counter = useRef(0);
  const notify = useCallback((title: string, body?: string, tone: SlipTone = "ink") => {
    counter.current += 1;
    setSlip({ id: counter.current, title, body, tone });
  }, []);

  useEffect(() => {
    if (!slip) return;
    const t = setTimeout(() => setSlip(null), 5200);
    return () => clearTimeout(t);
  }, [slip]);

  return (
    <Ctx.Provider value={notify}>
      {children}
      <div className="slip-dock" role="status" aria-live="polite">
        {slip && (
          <div key={slip.id} className={`slip slip--${slip.tone}`}>
            <p className="slip__title">{slip.title}</p>
            {slip.body && <p className="slip__body">{slip.body}</p>}
            <button type="button" className="slip__close" onClick={() => setSlip(null)} aria-label="Dismiss">×</button>
          </div>
        )}
      </div>
    </Ctx.Provider>
  );
}

export const useSlip = () => useContext(Ctx);
