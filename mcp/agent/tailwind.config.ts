import type { Config } from "tailwindcss";

/**
 * Phantom theme tokens.
 *
 * All colors resolve through CSS variables defined in app/globals.css —
 * `:root` carries the dark Ocean Navy palette (default) and
 * `[data-theme="light"]` overrides them with light-mode equivalents.
 * The shadcn-style HSL tokens use `hsl(var(--foo))`; the Material
 * Design 3 token surface uses `var(--m3-foo)` directly so the values
 * can be raw hex or rgba.
 *
 * Adding a new token: pick a name, declare it in BOTH `:root` and
 * `[data-theme="light"]` in globals.css, then alias it here.
 */
const config: Config = {
  darkMode: "class",
  content: [
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
    "./lib/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        // shadcn/ui HSL-token compatibility (dark/light overrides in
        // globals.css under :root and [data-theme="light"]).
        background: "hsl(var(--background))",
        foreground: "hsl(var(--foreground))",
        card: "hsl(var(--card))",
        "card-foreground": "hsl(var(--card-foreground))",
        popover: "hsl(var(--popover))",
        "popover-foreground": "hsl(var(--popover-foreground))",
        primary: "hsl(var(--primary))",
        "primary-foreground": "hsl(var(--primary-foreground))",
        secondary: "hsl(var(--secondary))",
        "secondary-foreground": "hsl(var(--secondary-foreground))",
        muted: "hsl(var(--muted))",
        "muted-foreground": "hsl(var(--muted-foreground))",
        accent: "hsl(var(--accent))",
        "accent-foreground": "hsl(var(--accent-foreground))",
        destructive: "hsl(var(--destructive))",
        "destructive-foreground": "hsl(var(--destructive-foreground))",
        border: "hsl(var(--border))",
        input: "hsl(var(--input))",
        ring: "hsl(var(--ring))",
        // Material Design 3 token surface — dark/light overrides in
        // globals.css under :root and [data-theme="light"].
        "surface-dim": "var(--m3-surface-dim)",
        "on-tertiary-fixed-variant": "var(--m3-on-tertiary-fixed-variant)",
        "on-secondary-fixed": "var(--m3-on-secondary-fixed)",
        "on-surface-variant": "var(--m3-on-surface-variant)",
        "surface-container-low": "var(--m3-surface-container-low)",
        "on-error": "var(--m3-on-error)",
        "outline-variant": "var(--m3-outline-variant)",
        "surface-container-highest": "var(--m3-surface-container-highest)",
        "secondary-fixed-dim": "var(--m3-secondary-fixed-dim)",
        "on-tertiary": "var(--m3-on-tertiary)",
        surface: "var(--m3-surface)",
        tertiary: "var(--m3-tertiary)",
        "on-background": "var(--m3-on-background)",
        "secondary-container": "var(--m3-secondary-container)",
        "inverse-primary": "var(--m3-inverse-primary)",
        "on-primary": "var(--m3-on-primary)",
        "on-error-container": "var(--m3-on-error-container)",
        "on-primary-fixed": "var(--m3-on-primary-fixed)",
        "surface-container-lowest": "var(--m3-surface-container-lowest)",
        "secondary-fixed": "var(--m3-secondary-fixed)",
        outline: "var(--m3-outline)",
        "surface-bright": "var(--m3-surface-bright)",
        "inverse-on-surface": "var(--m3-inverse-on-surface)",
        "on-tertiary-fixed": "var(--m3-on-tertiary-fixed)",
        "surface-container": "var(--m3-surface-container)",
        "primary-fixed": "var(--m3-primary-fixed)",
        "tertiary-container": "var(--m3-tertiary-container)",
        "on-secondary": "var(--m3-on-secondary)",
        "surface-variant": "var(--m3-surface-variant)",
        "tertiary-fixed": "var(--m3-tertiary-fixed)",
        "tertiary-fixed-dim": "var(--m3-tertiary-fixed-dim)",
        "surface-container-high": "var(--m3-surface-container-high)",
        "on-primary-container": "var(--m3-on-primary-container)",
        "primary-fixed-dim": "var(--m3-primary-fixed-dim)",
        "inverse-surface": "var(--m3-inverse-surface)",
        "surface-tint": "var(--m3-surface-tint)",
        "on-secondary-container": "var(--m3-on-secondary-container)",
        "on-tertiary-container": "var(--m3-on-tertiary-container)",
        "on-surface": "var(--m3-on-surface)",
        "on-secondary-fixed-variant": "var(--m3-on-secondary-fixed-variant)",
        "error-container": "var(--m3-error-container)",
        "on-primary-fixed-variant": "var(--m3-on-primary-fixed-variant)",
        "primary-container": "var(--m3-primary-container)",
        error: "var(--m3-error)",
        // Status glow accents — same hue across themes (intentional;
        // status colors should mean the same thing regardless of mode).
        "success-glow": "#56B55A",
        "error-glow": "#B72721",
        "warning-glow": "#E2A614",
        "info-glow": "#1963B3",
      },
      fontFamily: {
        sans: ["Manrope", "ui-sans-serif", "system-ui"],
        headline: ["Space Grotesk", "sans-serif"],
        body: ["Manrope", "sans-serif"],
        label: ["Manrope", "sans-serif"],
        mono: ["JetBrains Mono", "ui-monospace", "monospace"],
      },
      borderRadius: {
        DEFAULT: "0.25rem",
        lg: "0.5rem",
        xl: "0.75rem",
        full: "9999px",
      },
    },
  },
  plugins: [],
};

export default config;
