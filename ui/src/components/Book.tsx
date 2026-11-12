// The book's frame: crimson spine, index tabs, and the ruled sheet with its red margin rule.
import type { ReactNode } from "react";
import { NavLink, useLocation } from "react-router-dom";
import { useRef, useState } from "react";
import { useRhythm } from "../lib/rhythm";
import { applyTheme, nextTheme, readTheme, type ThemePref } from "../lib/theme";
import { AutoIcon, MoonIcon, SunIcon } from "./Icons";

export interface TabDef { to: string; label: string; count?: number }

export function Spine() {
  const [theme, setTheme] = useState<ThemePref>(readTheme);
  const cycle = () => {
    const next = nextTheme(theme);
    applyTheme(next);
    setTheme(next);
  };
  const label = theme === "system" ? "Theme: follows your system" : theme === "light" ? "Theme: day" : "Theme: lamplit";
  return (
    <aside className="spine" aria-label="Ledger">
      <span className="spine__band" aria-hidden="true" />
      <NavLink to="/" className="spine__mark" aria-label="Ledger home">
        बही-खाता <small>· LEDGER</small>
      </NavLink>
      <button type="button" className="spine__theme" onClick={cycle} aria-label={`${label}. Change theme`} title={label}>
        {theme === "system" ? <AutoIcon /> : theme === "light" ? <SunIcon /> : <MoonIcon />}
      </button>
    </aside>
  );
}

export function IndexTabs({ tabs }: { tabs: TabDef[] }) {
  return (
    <nav className="tabs" aria-label="Sections">
      {tabs.map((t, i) => (
        <NavLink key={t.to} to={t.to} end={t.to === "/"} className="tab">
          <span className="tab__num" aria-hidden="true">{String(i + 1).padStart(2, "0")}</span>
          <span>{t.label}</span>
          {t.count ? <span className="tab__count" aria-label={`${t.count} waiting`}>{t.count}</span> : <span />}
        </NavLink>
      ))}
      <span className="tabs__gap" />
    </nav>
  );
}

/** A ruled sheet. Re-keyed on route change so the load sequence plays once per page. */
export function Sheet({ children, aside }: { children: ReactNode; aside?: ReactNode }) {
  const { pathname } = useLocation();
  return <RuledSheet key={pathname} aside={aside}>{children}</RuledSheet>;
}

function RuledSheet({ children, aside }: { children: ReactNode; aside?: ReactNode }) {
  const body = useRef<HTMLDivElement>(null);
  useRhythm(body);   // keeps every block on the 28px ruling (lib/rhythm.ts)
  return (
    <main className="sheet" id="main">
      <div className="sheet__rules" aria-hidden="true" />
      <div className="sheet__margin" aria-hidden="true" />
      <div className="sheet__body" ref={body}>
        <div className="sheet__main">{children}</div>
        {aside && <aside className="marginalia" aria-label="Margin notes">{aside}</aside>}
      </div>
    </main>
  );
}

/** Page heading that starts left of the margin rule and crosses it. */
export function FolioHead({ kicker, title, children }: { kicker: string; title: string; children?: ReactNode }) {
  return (
    <header className="folio-head">
      <p className="kicker">{kicker}</p>
      <h1 className="h-page">{title}</h1>
      {children && <p>{children}</p>}
    </header>
  );
}

export function Section({ title, kicker, children, className = "" }: { title: string; kicker?: string; children: ReactNode; className?: string }) {
  return (
    <section className={`section ${className}`}>
      {kicker && <p className="kicker">{kicker}</p>}
      <h2 className="h-section">{title}</h2>
      {children}
    </section>
  );
}
