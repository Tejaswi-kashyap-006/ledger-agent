// Line icons drawn for this app: 1.5px strokes, round caps, currentColor. Decorative by default (aria-hidden);
// every icon sits next to a text label, so meaning never depends on the glyph alone.
import type { SVGProps } from "react";

type P = SVGProps<SVGSVGElement> & { size?: number };

function Svg({ size = 16, children, ...rest }: P) {
  return (
    <svg width={size} height={size} viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth={1.5}
      strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false" {...rest}>
      {children}
    </svg>
  );
}

export const TickIcon = (p: P) => <Svg {...p}><path d="M3 8.5 6.5 12 13 4.5" /></Svg>;
export const CrossIcon = (p: P) => <Svg {...p}><path d="M4 4l8 8M12 4l-8 8" /></Svg>;
export const AlertIcon = (p: P) => (
  <Svg {...p}><path d="M8 2.5 14.5 13.5h-13z" /><path d="M8 6.5v3.2M8 11.6v.1" /></Svg>
);
export const RuleIcon = (p: P) => (
  <Svg {...p}><path d="M2.5 4.5h11M2.5 8h11M2.5 11.5h7" /><circle cx="12.2" cy="11.5" r="1.3" /></Svg>
);
export const PencilIcon = (p: P) => (
  <Svg {...p}><path d="M10.5 2.5l3 3-8 8H2.5v-3z" /><path d="M9 4l3 3" /></Svg>
);
export const ScaleIcon = (p: P) => (
  <Svg {...p}><path d="M8 2.5v11M4.5 13.5h7M3 5h10" /><path d="M3 5 1.5 9h3zM13 5l-1.5 4h3z" /></Svg>
);
export const EyeIcon = (p: P) => (
  <Svg {...p}><path d="M1.5 8S4 3.5 8 3.5 14.5 8 14.5 8 12 12.5 8 12.5 1.5 8 1.5 8z" /><circle cx="8" cy="8" r="2" /></Svg>
);
export const UploadIcon = (p: P) => (
  <Svg {...p}><path d="M8 11V2.5M4.5 6 8 2.5 11.5 6" /><path d="M2.5 10.5v3h11v-3" /></Svg>
);
export const ArrowUpIcon = (p: P) => <Svg {...p}><path d="M8 13V3M4 7l4-4 4 4" /></Svg>;
export const ArrowDownIcon = (p: P) => <Svg {...p}><path d="M8 3v10M4 9l4 4 4-4" /></Svg>;
export const SunIcon = (p: P) => (
  <Svg {...p}><circle cx="8" cy="8" r="3" /><path d="M8 1v1.6M8 13.4V15M1 8h1.6M13.4 8H15M3 3l1.1 1.1M11.9 11.9 13 13M3 13l1.1-1.1M11.9 4.1 13 3" /></Svg>
);
export const MoonIcon = (p: P) => <Svg {...p}><path d="M13.5 9.5A5.5 5.5 0 1 1 6.5 2.5a4.5 4.5 0 0 0 7 7z" /></Svg>;
export const AutoIcon = (p: P) => (
  <Svg {...p}><circle cx="8" cy="8" r="5.5" /><path d="M8 2.5v11" /><path d="M8 2.5a5.5 5.5 0 0 1 0 11z" fill="currentColor" stroke="none" /></Svg>
);
export const SearchIcon = (p: P) => <Svg {...p}><circle cx="7" cy="7" r="4.5" /><path d="M10.5 10.5 14 14" /></Svg>;
export const ChevronIcon = (p: P) => <Svg {...p}><path d="M4 6l4 4 4-4" /></Svg>;
