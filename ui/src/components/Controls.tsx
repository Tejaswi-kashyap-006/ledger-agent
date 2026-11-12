// Buttons and fields. Fields sit on a rule line - no boxes (DESIGN.md "Field").
import { forwardRef, useId, type ButtonHTMLAttributes, type InputHTMLAttributes, type ReactNode,
  type SelectHTMLAttributes, type TextareaHTMLAttributes } from "react";

type ButtonVariant = "ink" | "quiet" | "stamp";

export function Button({ variant = "ink", className = "", ...rest }: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: ButtonVariant }) {
  return <button type="button" className={`btn btn--${variant} ${className}`} {...rest} />;
}

interface FieldShell { label: string; hint?: ReactNode; className?: string }

export const TextField = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement> & FieldShell>(
  function TextField({ label, hint, className = "", id, ...rest }, ref) {
    const auto = useId();
    const fid = id ?? auto;
    return (
      <div className={`field ${className}`}>
        <label className="kicker field__label" htmlFor={fid}>{label}</label>
        <input ref={ref} id={fid} className="field__input" aria-describedby={hint ? `${fid}-hint` : undefined} {...rest} />
        {hint && <p id={`${fid}-hint`} className="field__hint">{hint}</p>}
      </div>
    );
  },
);

export function SelectField({ label, hint, className = "", id, children, ...rest }: SelectHTMLAttributes<HTMLSelectElement> & FieldShell) {
  const auto = useId();
  const fid = id ?? auto;
  return (
    <div className={`field ${className}`}>
      <label className="kicker field__label" htmlFor={fid}>{label}</label>
      <select id={fid} className="field__input field__select" {...rest}>{children}</select>
      {hint && <p className="field__hint">{hint}</p>}
    </div>
  );
}

export function TextArea({ label, hint, className = "", id, ...rest }: TextareaHTMLAttributes<HTMLTextAreaElement> & FieldShell) {
  const auto = useId();
  const fid = id ?? auto;
  return (
    <div className={`field ${className}`}>
      <label className="kicker field__label" htmlFor={fid}>{label}</label>
      <textarea id={fid} className="field__input field__area" {...rest} />
      {hint && <p className="field__hint">{hint}</p>}
    </div>
  );
}

/** Loading and error states, written like notes on the page rather than spinners. */
export function Loading({ what }: { what: string }) {
  return <p className="note note--loading" role="status">Turning to {what}…</p>;
}

export function ErrorNote({ error, onRetry }: { error: Error; onRetry?: () => void }) {
  return (
    <div className="note note--error" role="alert">
      <p><strong>Couldn't read the ledger.</strong> {error.message}</p>
      {onRetry && <Button variant="quiet" onClick={onRetry}>Try again</Button>}
    </div>
  );
}
