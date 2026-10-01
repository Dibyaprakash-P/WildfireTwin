/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        mono: ['"JetBrains Mono"', "ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
        sans: ["Inter", "system-ui", "sans-serif"],
      },
      colors: {
        bg: "rgb(var(--c-bg) / <alpha-value>)",
        panel: "rgb(var(--c-panel) / <alpha-value>)",
        raised: "rgb(var(--c-raised) / <alpha-value>)",
        line: "rgb(var(--c-line) / <alpha-value>)",
        ink: "rgb(var(--c-ink) / <alpha-value>)",
        head: "rgb(var(--c-head) / <alpha-value>)",
        dim: "rgb(var(--c-dim) / <alpha-value>)",
        fire: "rgb(var(--c-fire) / <alpha-value>)",
        ok: "rgb(var(--c-ok) / <alpha-value>)",
        warn: "rgb(var(--c-warn) / <alpha-value>)",
        crit: "rgb(var(--c-crit) / <alpha-value>)",
        info: "rgb(var(--c-info) / <alpha-value>)",
      },
      fontSize: { "2xs": ["10px", "14px"], xs: ["11px", "16px"], sm: ["12px", "18px"] },
      borderRadius: { DEFAULT: "2px", sm: "1px" },
    },
  },
  plugins: [],
};
