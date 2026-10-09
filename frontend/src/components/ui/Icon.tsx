import type { SVGProps } from "react";

/** Minimal stroke icon set (24px grid, currentColor). */
const PATHS: Record<string, string> = {
  overview: "M4 13h6V4H4v9Zm0 7h6v-5H4v5Zm10 0h6v-9h-6v9Zm0-16v5h6V4h-6Z",
  lab: "M9 3h6M10 3v6L4.5 18.5A1.6 1.6 0 0 0 5.9 21h12.2a1.6 1.6 0 0 0 1.4-2.5L14 9V3M7.5 15h9",
  runs: "M4 6h16M4 12h10M4 18h7M17 15l3 3-3 3",
  perf: "M3 20h18M6 16v-4M10 16V8M14 16v-6M18 16V5",
  quality: "M9 12l2 2 4-4M12 3l7 3v5c0 4.5-3 8.3-7 10-4-1.7-7-5.5-7-10V6l7-3Z",
  anomaly: "M3 17l5-6 4 4 4-7 5 9M3 21h18",
  security: "M12 3l8 3v6c0 4.4-3.4 8.2-8 9-4.6-.8-8-4.6-8-9V6l8-3Zm0 6v4m0 3h.01",
  sql: "M4 6c0-1.7 3.6-3 8-3s8 1.3 8 3-3.6 3-8 3-8-1.3-8-3Zm0 0v12c0 1.7 3.6 3 8 3s8-1.3 8-3V6M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3",
  compare: "M8 4v16M16 4v16M4 8h4M4 14h4M16 10h4M16 17h4",
  assistant: "M21 12a8 8 0 0 1-11.8 7L4 20l1.1-4.6A8 8 0 1 1 21 12ZM8.5 11h.01M12 11h.01M15.5 11h.01",
  pipeline: "M4 7h4v4H4zM16 13h4v4h-4zM10 4h4v4h-4zM8 9h4M12 8v7h4",
  reports: "M7 3h7l5 5v13H7V3Zm7 0v5h5M10 13h6M10 17h6",
  check: "M5 12.5l4.5 4.5L19 7.5",
  x: "M6 6l12 12M18 6L6 18",
  alert: "M12 4l9 16H3l9-16Zm0 6v4m0 3h.01",
  info: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18Zm0-10v6m0-9h.01",
  minus: "M6 12h12",
  dot: "M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6Z",
  diamond: "M12 3l9 9-9 9-9-9 9-9Z",
  question: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18Zm-2.5-11.5a2.5 2.5 0 1 1 3.5 2.3c-.6.3-1 .9-1 1.6V14m0 3h.01",
  refresh: "M20 11a8 8 0 0 0-14.3-4.9L4 8m0-4v4h4M4 13a8 8 0 0 0 14.3 4.9L20 16m0 4v-4h-4",
  chevronLeft: "M15 6l-6 6 6 6",
  chevronRight: "M9 6l6 6-6 6",
  chevronDown: "M6 9l6 6 6-6",
  menu: "M4 6h16M4 12h16M4 18h16",
  external: "M14 4h6v6M20 4l-9 9M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5",
  download: "M12 4v11m0 0l-4-4m4 4l4-4M5 20h14",
  play: "M7 5v14l11-7L7 5Z",
  stop: "M7 7h10v10H7z",
  search: "M11 18a7 7 0 1 0 0-14 7 7 0 0 0 0 14Zm9 2-4-4",
  table: "M4 5h16v14H4zM4 10h16M4 15h16M10 5v14",
  chart: "M4 20V10M10 20V4M16 20v-7M22 20H2",
  sun: "M12 17a5 5 0 1 0 0-10 5 5 0 0 0 0 10Zm0-15v2m0 16v2M4.9 4.9l1.4 1.4m11.4 11.4 1.4 1.4M2 12h2m16 0h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4",
  moon: "M20 14.5A8 8 0 0 1 9.5 4 8 8 0 1 0 20 14.5Z",
  monitor: "M3 5h18v11H3zM8 20h8M12 16v4",
  flag: "M5 21V4m0 0h11l-2 4 2 4H5",
  link: "M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1",
  collapse: "M15 6l-6 6 6 6M20 4v16",
  expand: "M9 6l6 6-6 6M4 4v16",
};

export type IconName = keyof typeof PATHS;

export function Icon({ name, size = 16, className, ...rest }: { name: IconName; size?: number } & SVGProps<SVGSVGElement>) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.8}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
      className={className}
      {...rest}
    >
      <path d={PATHS[name]} />
    </svg>
  );
}
