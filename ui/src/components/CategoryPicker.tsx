// Keyboard-first category combobox (WAI-ARIA combobox + listbox pattern).
// Type to filter ("food del" matches "Food:Delivery"), arrows to move, Enter to choose, Escape to close.
import { forwardRef, useId, useMemo, useState, type KeyboardEvent } from "react";
import { splitCategory } from "../lib/format";

interface Props {
  categories: readonly string[];
  onSelect: (category: string) => void;
  label?: string;
  placeholder?: string;
  autoFocus?: boolean;
  className?: string;
  hideLabel?: boolean;
}

export function matchCategories(categories: readonly string[], query: string): string[] {
  const words = query.toLowerCase().split(/[\s:]+/).filter(Boolean);
  if (!words.length) return [...categories];
  return categories.filter((c) => {
    const hay = c.toLowerCase();
    return words.every((w) => hay.includes(w));
  });
}

export const CategoryPicker = forwardRef<HTMLInputElement, Props>(function CategoryPicker(
  { categories, onSelect, label = "Category", placeholder = "Type to find a category", autoFocus, className = "", hideLabel },
  ref,
) {
  const id = useId();
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const options = useMemo(() => matchCategories(categories, query), [categories, query]);
  const listId = `${id}-list`;
  const optId = (i: number) => `${id}-opt-${i}`;

  const choose = (c: string | undefined) => {
    if (!c) return;
    onSelect(c);
    setQuery("");
    setOpen(false);
    setActive(0);
  };

  const onKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setOpen(true);
      setActive((a) => Math.min(a + 1, options.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActive((a) => Math.max(a - 1, 0));
    } else if (e.key === "Enter") {
      if (open || query) {
        e.preventDefault();
        e.stopPropagation();
        choose(options[active]);
      }
    } else if (e.key === "Escape") {
      e.stopPropagation();
      setOpen(false);
      setQuery("");
    }
  };

  return (
    <div className={`picker ${className}`}>
      <label className={hideLabel ? "sr-only" : "kicker field__label"} htmlFor={id}>{label}</label>
      <input
        ref={ref}
        id={id}
        className="field__input picker__input"
        role="combobox"
        aria-expanded={open}
        aria-controls={listId}
        aria-autocomplete="list"
        aria-activedescendant={open && options.length ? optId(active) : undefined}
        autoComplete="off"
        spellCheck={false}
        autoFocus={autoFocus}
        placeholder={placeholder}
        value={query}
        onChange={(e) => { setQuery(e.target.value); setOpen(true); setActive(0); }}
        onFocus={() => setOpen(true)}
        onBlur={() => setTimeout(() => setOpen(false), 120)}
        onKeyDown={onKeyDown}
      />
      {open && (
        <ul id={listId} role="listbox" className="picker__list" aria-label={label}>
          {options.length === 0 && <li className="picker__empty" role="presentation">No category matches “{query}”.</li>}
          {options.map((c, i) => {
            const { group, name } = splitCategory(c);
            return (
              <li
                key={c}
                id={optId(i)}
                role="option"
                aria-selected={i === active}
                className="picker__opt"
                onMouseDown={(e) => { e.preventDefault(); choose(c); }}
                onMouseEnter={() => setActive(i)}
              >
                {group && <span className="picker__group">{group}</span>}
                <span>{name}</span>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
});
