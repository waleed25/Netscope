import type { Config } from "tailwindcss";

/**
 * Helper: reference a CSS custom property as an RGB color with alpha support.
 * Usage in classes: `bg-accent`, `bg-accent/10`, `text-foreground/80`, etc.
 */
const v = (name: string) => `rgb(var(--color-${name}) / <alpha-value>)`;

const config: Config = {
  darkMode: "class",
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        background:       v("background"),
        surface:          v("surface"),
        "surface-hover":  v("surface-hover"),
        "surface-active": v("surface-active"),
        border:           v("border"),
        "border-subtle":  v("border-subtle"),
        foreground:       v("foreground"),
        muted:            v("muted"),
        "muted-dim":      v("muted-dim"),
        accent:           v("accent"),
        success:          v("success"),
        warning:          v("warning"),
        danger:           v("danger"),
        purple:           v("purple"),
        // Extended semantic colors
        "accent-muted":   v("accent-muted"),
        severe:           v("severe"),
        pink:             v("pink"),
        "accent-emphasis":       v("accent-emphasis"),
        "success-emphasis":      v("success-emphasis"),
        "danger-emphasis":       v("danger-emphasis"),
        "purple-emphasis":       v("purple-emphasis"),
        tool:                    v("tool"),
        attention:               v("attention"),
        "success-subtle":        v("success-subtle"),
        "danger-subtle":         v("danger-subtle"),
        "warning-subtle":        v("warning-subtle"),
        "accent-subtle":         v("accent-subtle"),
        "purple-subtle":         v("purple-subtle"),
        "muted-extra":           v("muted-extra"),
        "success-emphasis-hover": v("success-emphasis-hover"),
        "accent-emphasis-hover":  v("accent-emphasis-hover"),
        "danger-emphasis-hover":  v("danger-emphasis-hover"),
        "purple-emphasis-hover":  v("purple-emphasis-hover"),
        "ok-bg":                 v("ok-bg"),
        "down-bg":               v("down-bg"),
        "brand-telegram":        v("brand-telegram"),
        "brand-whatsapp":        v("brand-whatsapp"),
        protocol: {
          HTTP:  v("protocol-http"),
          HTTPS: v("protocol-http"),
          TLS:   v("protocol-tls"),
          DNS:   v("protocol-dns"),
          TCP:   v("protocol-tcp"),
          UDP:   v("protocol-udp"),
          ICMP:  v("protocol-icmp"),
          ARP:   v("protocol-arp"),
          OTHER: v("protocol-other"),
        },
      },
      fontFamily: {
        sans: ["Inter", "system-ui", "-apple-system", "sans-serif"],
        mono: ["JetBrains Mono", "Fira Code", "Cascadia Code", "monospace"],
      },
    },
  },
  plugins: [],
};

export default config;
