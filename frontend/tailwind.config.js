/** @type {import('tailwindcss').Config} */
// All colors resolve to CSS custom properties defined in src/index.css, so light/dark
// switching happens in one place (prefers-color-scheme, or the data-theme override).
const token = (name) => `rgb(var(--${name}) / <alpha-value>)`;

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        page: token("page"),
        surface: token("surface"),
        "surface-2": token("surface-2"),
        line: token("line"),
        "line-strong": token("line-strong"),
        ink: token("ink"),
        "ink-2": token("ink-2"),
        muted: token("muted"),
        accent: token("accent"),
        "accent-ink": token("accent-ink"),
        "accent-strong": token("accent-strong"),
        good: token("good"),
        warning: token("warning"),
        serious: token("serious"),
        critical: token("critical"),
        "good-ink": token("good-ink"),
        "warning-ink": token("warning-ink"),
        "serious-ink": token("serious-ink"),
        "critical-ink": token("critical-ink"),
      },
      fontFamily: {
        sans: ["system-ui", "-apple-system", "Segoe UI", "Roboto", "sans-serif"],
        mono: ["ui-monospace", "SFMono-Regular", "Cascadia Code", "Consolas", "monospace"],
      },
      fontSize: {
        "2xs": ["0.6875rem", { lineHeight: "1rem" }],
      },
    },
  },
  plugins: [],
};
