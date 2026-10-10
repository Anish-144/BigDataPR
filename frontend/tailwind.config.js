/** @type {import('tailwindcss').Config} */
const token = (name) => `rgb(var(--${name}) / <alpha-value>)`;

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  darkMode: ['class', '[data-theme="dark"]'],
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
        secondary: token("secondary"),
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
        sans: ["Inter", "Manrope", "system-ui", "-apple-system", "sans-serif"],
        mono: ["ui-monospace", "SFMono-Regular", "Cascadia Code", "Consolas", "monospace"],
      },
      fontSize: {
        "2xs": ["0.6875rem", { lineHeight: "1rem" }],
      },
      boxShadow: {
        'subtle': '0 1px 2px 0 rgba(0, 0, 0, 0.05)',
        'elevated': '0 4px 6px -1px rgba(0, 0, 0, 0.05), 0 2px 4px -1px rgba(0, 0, 0, 0.03)',
      }
    },
  },
  plugins: [],
};
