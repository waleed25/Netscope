# NetScope Desktop — UI Design Language Guide

> **Purpose:** This document is the single source of truth for the NetScope visual design language. Any agent or developer recreating, extending, or porting the UI must follow these specifications exactly.

---

## Table of Contents

1. [Design Philosophy](#1-design-philosophy)
2. [Reference Screenshots](#2-reference-screenshots)
3. [Color System](#3-color-system)
4. [Typography](#4-typography)
5. [Spacing & Layout](#5-spacing--layout)
6. [Component Patterns](#6-component-patterns)
7. [Interaction & Animation](#7-interaction--animation)
8. [Protocol Visualization](#8-protocol-visualization)
9. [Tailwind Class Reference](#9-tailwind-class-reference)
10. [Do's and Don'ts](#10-dos-and-donts)

---

## 1. Design Philosophy

### North Star: "The Analytical Architect"

NetScope is a **professional network analysis tool**, not a consumer dashboard. The UI must communicate:

- **Precision** — every pixel serves a function
- **Density** — maximum information in minimum space
- **Calm authority** — data-forward, never decorative

The visual language draws from **macOS Sequoia / Sonoma** native apps and **GitHub's** dark/light palettes. It is inspired by instruments (Wireshark, Terminal, Activity Monitor) not SaaS products.

### Core Principles

| Principle | Rule |
|---|---|
| **Tonal Structuralism** | Depth is expressed through surface tone shifts, never with 1px divider lines |
| **Compact Density** | Base font is 13px. Padding is measured in 2–4px increments, not 16–24px |
| **Semantic Color** | Every color serves a functional role. No decorative use of color |
| **Dark-first** | Dark mode is the primary experience. Light mode mirrors it with inverted token values |
| **No pure black on white** | Foreground text uses `#1c1c1e` (Apple iOS system label), never `#000000` |
| **Max 4px radius** | Corner rounding is capped at `rounded` (4px). No pill shapes, no large radii |
| **No drop shadows** | Elements are separated by surface tone, not box shadows |

---

## 2. Reference Screenshots

These screens were generated with Google Stitch and represent the target visual fidelity.

### Screen 1 — Main Dashboard (Light Mode)

![NetScope Dashboard Light Mode](https://lh3.googleusercontent.com/aida/ADBb0uhdx_hRcrEUtcvVkk02VrYWA09Iu8D4TpfaVrg2jWBE39T2zwbyJ8OwEDPSgSID_ti2GFf-BuZvptTNAICzd3Dl6CG7BcW5O13od5S23F1q2W1lFvI63Q_KvW4Lqu5r8zjXpdiLmgzHaGGoPaxpuJIKLNNfWRGTsIKT4lezO4OZ30a9eu_KJs1ocjzSMFaEEfWPkzgU_p-u1j3b-6Ek_phrcFFb45q9ZBBhhgSaq2xolU7wfKZogJPV1g)

**Key elements visible:**
- 48px icon-only sidebar with blue active state
- Packet capture table with protocol color badges
- 320px AI chat panel (right side)
- Bottom status bar
- Off-white background `#f9f9fe`, surface `#f0f0f5`

---

### Screen 2 — Main Dashboard (Dark Mode)

![NetScope Dashboard Dark Mode](https://lh3.googleusercontent.com/aida/ADBb0uhECgWbb2HywFt5ZTu2m__jynZa-yn5t_NZrF0ZwJZ5dBuWOw_YqGZ_h7j7-ti1P1sNbKdVVJUS1aGmA4aolR2RsyLdlkyQSlEpw4HiDJjbTM3cXi_Ym5tYPfMeQFyE3iiZ41TzBEsPd4x_-iBl4YO9VqpSX4QylQ6YYDEjTGaQjSxu1gPFIWM16-DpmkB7b57-UK8tc-3XCmuSEAy5EJQywmtFvX0TwLmImVPQh8K0oedgiVKsu3xG-uA)

**Key elements visible:**
- Wireshark-style protocol row tinting (TCP=blue-tint, TLS=indigo-tint, DNS=green-tint, etc.)
- AI panel with assistant message (2px blue left-border) + user bubble (accent/20 bg)
- Token counter at top of AI panel
- Near-black background `#0a0a0b`

---

### Screen 3 — Network Tools Panel (Light Mode)

![NetScope Network Tools](https://lh3.googleusercontent.com/aida/ADBb0ugzzN5F7Fxt01rXOybsh6fjxdJ-r2O-bCs7zymnvrkPBdIpPBZ592v4AiQ3rQJGmeS3PX3yoaFoqBXVZokPPW3ksUsAI7r5hVQLujVq0EYWp-vFHJn0GrBcMuC45u-TK3uOCFfFBfSqyhZA4sxBeiKt6L23ZAMIT5r2g1sEoS-4nvi5pbSxG0jDa74s3RLHsE4cyctwu-u5khsiSbX9oEhlWwXsKJng2_UoNs_2-BPzGg8Qu0fz2L2dhFU)

**Key elements visible:**
- Horizontal tab bar with blue underline active state
- Compact toolbar: small inputs + action buttons
- Dense scan results table with colored status badges
- Total count footer

---

## 3. Color System

All colors are defined as CSS custom properties in `frontend/src/index.css` and consumed via Tailwind utility classes.

### 3.1 Light Theme Tokens

| Token | CSS Variable | Hex | Usage |
|---|---|---|---|
| Background | `--color-background` | `#f9f9fe` | Page/app background |
| Surface | `--color-surface` | `#f0f0f5` | Cards, panels, sidebars |
| Surface Hover | `--color-surface-hover` | `#e2e2e8` | Hover state for surface elements |
| Surface Active | `--color-surface-active` | `#d0d0d8` | Pressed/active state |
| Border | `--color-border` | `#d2d2d8` | All borders and dividers |
| Border Subtle | `--color-border-subtle` | `#e2e2e8` | De-emphasized borders |
| **Foreground** | `--color-foreground` | `#1c1c1e` | **Primary text — Apple iOS label** |
| Muted | `--color-muted` | `#636c76` | Secondary text, labels |
| Muted Dim | `--color-muted-dim` | `#98a0a8` | Tertiary text, placeholders, timestamps |
| Accent | `--color-accent` | `#0066ff` | Interactive elements, links, focus |
| Success | `--color-success` | `#24ae4b` | Online status, passing states |
| Warning | `--color-warning` | `#d77d00` | Caution indicators |
| Danger | `--color-danger` | `#dc3026` | Errors, offline status |
| Purple | `--color-purple` | `#953ac4` | AI/insight indicators |

### 3.2 Dark Theme Tokens

| Token | CSS Variable | Hex | Usage |
|---|---|---|---|
| Background | `--color-background` | `#0a0a0b` | Page/app background |
| Surface | `--color-surface` | `#0d1117` | Cards, panels (GitHub dark) |
| Surface Hover | `--color-surface-hover` | `#161b22` | Hover state |
| Surface Active | `--color-surface-active` | `#1c2128` | Active/pressed state |
| Border | `--color-border` | `#21262d` | Borders (GitHub dark) |
| Border Subtle | `--color-border-subtle` | `#30363d` | Subtle separators |
| **Foreground** | `--color-foreground` | `#e2e8f0` | **Primary text — near white** |
| Muted | `--color-muted` | `#8b949e` | Secondary text |
| Muted Dim | `--color-muted-dim` | `#4a5568` | Tertiary text, disabled |
| Accent | `--color-accent` | `#58a6ff` | Interactive (GitHub blue) |
| Success | `--color-success` | `#3fb950` | Online / passing |
| Warning | `--color-warning` | `#d29922` | Caution |
| Danger | `--color-danger` | `#f85149` | Error / offline |

### 3.3 Semantic Subtle Colors

These are used for status pills, alert backgrounds, and diff indicators:

| Token | Light | Dark | Usage |
|---|---|---|---|
| `--color-success-subtle` | `#d4f7de` | `#0d2b1a` | Success badge background |
| `--color-danger-subtle` | `#fee4e2` | `#2b0e0e` | Error badge background |
| `--color-warning-subtle` | `#fff4bb` | `#2b1f07` | Warning badge background |
| `--color-accent-subtle` | `#d5eeff` | `#0d1f3c` | Info badge background |
| `--color-purple-subtle` | `#f5e9ff` | `#1b1030` | AI/insight badge background |

### 3.4 How to Use Colors in Code

```tsx
// Tailwind CSS (preferred)
<div className="bg-surface text-foreground border border-border" />
<span className="text-muted" />
<button className="bg-accent text-white hover:bg-accent/90" />

// With opacity variants
<div className="bg-accent/10" />  // accent at 10% opacity
<div className="bg-danger/20" />  // danger at 20% opacity

// CSS custom property directly
color: rgb(var(--color-foreground));
background: rgb(var(--color-surface) / 0.8);
```

---

## 4. Typography

### Font Stack

```css
font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto,
             Helvetica, Arial, sans-serif,
             "Apple Color Emoji", "Segoe UI Emoji";
```

Tailwind config also provides:
- **Sans:** `Inter, system-ui, -apple-system, sans-serif`
- **Mono:** `JetBrains Mono, Fira Code, Cascadia Code, monospace`

### Scale

| Role | Size | Weight | Class | Color |
|---|---|---|---|---|
| Page title | 16px | 600 | `text-base font-semibold` | `text-foreground` |
| Section heading | 13px | 600 | `text-xs font-semibold` | `text-foreground` |
| **Body / data (standard)** | **13px** | **400** | **`text-xs`** | **`text-foreground`** |
| Secondary text | 13px | 400 | `text-xs` | `text-muted` |
| Meta label | 11px | 500 | `text-[11px] font-medium` | `text-muted-dim` |
| Caption / timestamp | 11px | 400 | `text-[11px]` | `text-muted-dim` |
| Prompt chip | 10px | 400 | `text-[10px]` | `text-muted` |

### Special Rule: `.label-meta`

Used for uppercase section labels (e.g., column headers in settings panels):

```css
.label-meta {
  font-size: 11px;
  font-weight: 500;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: rgb(var(--color-muted-dim));
}
```

### Monospace Data

Timestamps, hex values, IP addresses, port numbers — always use tabular numerics:

```tsx
<span className="font-mono text-xs tabular-nums text-muted">
  192.168.1.105
</span>
```

---

## 5. Spacing & Layout

### 5.1 Overall App Layout

```
┌──────────────────────────────────────────────────────────┐
│  48px  │          Main Content Area          │  320px AI  │
│ Sidebar│          (flex-1, overflow-auto)     │  Panel     │
│        │                                     │ (optional) │
└──────────────────────────────────────────────────────────┘
```

- **Sidebar:** `w-12` (48px), fixed, flex column, `bg-surface`, `border-r border-border`
- **Main content:** `flex-1`, has its own internal tab/toolbar/content layout
- **AI Panel:** `w-80` (320px), slides in from right via `width` transition

### 5.2 Sidebar Structure

```tsx
<aside className="w-12 flex flex-col shrink-0 bg-surface border-r border-border">
  {/* Logo — 40px */}
  <div className="h-10 flex items-center justify-center shrink-0" />

  {/* Nav items — fills remaining space */}
  <nav className="flex-1 flex flex-col items-center py-1 gap-0.5 overflow-y-auto">
    <SidebarItem icon={Activity} id="packets" />
    {/* ... more items */}
  </nav>

  {/* Bottom controls */}
  <div className="shrink-0 flex flex-col items-center pb-2 gap-1">
    {/* AI toggle, theme toggle */}
  </div>
</aside>
```

**SidebarItem states:**

```tsx
// Active
className="w-full h-8 flex items-center justify-center rounded-md mx-auto
           text-accent bg-accent/10"
style={{ boxShadow: "inset -2px 0 0 rgb(var(--color-accent))" }}

// Inactive
className="w-full h-8 flex items-center justify-center rounded-md mx-auto
           text-muted-dim hover:text-foreground hover:bg-surface-hover
           transition-colors"
```

### 5.3 Spacing Scale

NetScope uses a **tight 4px grid**. These are the permitted padding/gap values:

| Value | px | Tailwind |
|---|---|---|
| Micro | 2px | `p-0.5`, `gap-0.5` |
| Tight | 4px | `p-1`, `gap-1` |
| Standard | 6px | `p-1.5`, `gap-1.5` |
| Comfortable | 8px | `p-2`, `gap-2` |
| Loose | 12px | `p-3`, `gap-3` |

Toolbar rows typically use `gap-2` between controls, `px-2 py-1.5` for buttons, `px-3 py-2` for table cells.

### 5.4 Toolbar Pattern

Every tab view has a toolbar row at the top:

```tsx
<div className="flex items-center gap-2 flex-wrap px-3 py-2 border-b border-border bg-surface shrink-0">
  <SomeIcon className="w-4 h-4 text-accent shrink-0" />
  <input
    className="bg-background border border-border rounded px-2 py-1 text-xs
               text-foreground placeholder-muted-dim focus:outline-none focus:border-accent w-36"
  />
  <button
    className="flex items-center gap-1.5 px-2.5 py-1.5 rounded text-xs font-medium
               bg-accent text-white hover:bg-accent/90 transition-colors disabled:opacity-50"
  />
</div>
```

---

## 6. Component Patterns

### 6.1 Input Field

```tsx
<input
  className="bg-background border border-border rounded px-2 py-1 text-xs
             text-foreground placeholder-muted-dim
             focus:outline-none focus:border-accent
             disabled:opacity-50"
/>
```

Focus state: border changes to `--color-accent`. No ring/glow.

### 6.2 Button Variants

**Primary (solid accent):**
```tsx
<button className="flex items-center gap-1.5 px-2.5 py-1.5 rounded text-xs font-medium
                   bg-accent text-white hover:bg-accent/90 transition-colors
                   disabled:opacity-50 disabled:cursor-not-allowed">
  <Play className="w-3 h-3" /> Start Scan
</button>
```

**Ghost (border only):**
```tsx
<button className="flex items-center gap-1.5 px-2.5 py-1.5 rounded text-xs font-medium
                   border border-border text-muted
                   hover:text-accent hover:border-accent transition-colors">
  <Download className="w-3 h-3" /> Export CSV
</button>
```

**Icon-only (sidebar):**
```tsx
<button className="w-8 h-8 flex items-center justify-center rounded
                   text-muted-dim hover:text-foreground hover:bg-surface-hover transition-colors">
  <Settings className="w-4 h-4" />
</button>
```

### 6.3 Table

```tsx
<table className="w-full text-xs">
  <thead>
    <tr className="border-b border-border bg-surface text-muted sticky top-0">
      <th className="px-3 py-2 text-left font-medium whitespace-nowrap">
        Source IP
      </th>
    </tr>
  </thead>
  <tbody>
    <tr className="border-b border-border hover:bg-surface-hover transition-colors cursor-pointer">
      <td className="px-3 py-2 font-mono text-foreground">192.168.1.5</td>
    </tr>
  </tbody>
</table>
```

Row selection: `outline: 2px solid rgb(var(--color-accent)); outline-offset: -2px`

### 6.4 Tab Bar

```tsx
<div className="flex items-center border-b border-border bg-surface shrink-0 overflow-x-auto">
  {tabs.map(tab => (
    <button
      key={tab.id}
      className={`flex items-center gap-1.5 px-3 py-2 text-xs font-medium whitespace-nowrap
                  border-b-2 transition-colors
                  ${active === tab.id
                    ? "border-accent text-accent"
                    : "border-transparent text-muted hover:text-foreground"}`}
    >
      <tab.icon className="w-3.5 h-3.5" />
      {tab.label}
    </button>
  ))}
</div>
```

### 6.5 Status Badge / Pill

```tsx
// Online
<span className="px-1.5 py-0.5 rounded text-[10px] font-medium
                 bg-success-subtle text-success">Online</span>

// Offline
<span className="px-1.5 py-0.5 rounded text-[10px] font-medium
                 bg-danger-subtle text-danger">Offline</span>

// Protocol badge
<span className="px-1.5 py-0.5 rounded text-[10px] font-medium
                 text-protocol-TCP bg-protocol-TCP">TCP</span>
```

### 6.6 AI Chat Panel

```tsx
{/* Container */}
<aside className="w-80 flex flex-col border-l border-border bg-background">

  {/* Token counter header */}
  <div className="flex items-center justify-center px-2 py-1.5 border-b border-border shrink-0">
    <TokenCounter />
  </div>

  {/* Messages */}
  <div className="flex-1 overflow-y-auto px-3 py-2 flex flex-col gap-2">

    {/* Assistant message */}
    <div className="bg-surface border-l-2 border-accent rounded px-3 py-2">
      <div className="text-[10px] font-mono text-muted mb-1">assistant</div>
      <div className="text-xs text-foreground leading-relaxed">{content}</div>
    </div>

    {/* User message */}
    <div className="flex justify-end">
      <div className="bg-accent/20 rounded px-3 py-2 max-w-[85%]">
        <div className="text-xs text-foreground">{content}</div>
      </div>
    </div>

  </div>

  {/* Prompt chips */}
  <div className="px-2 py-1.5 flex flex-wrap gap-1 border-t border-border shrink-0">
    <button className="px-2 py-0.5 bg-surface border border-border rounded
                       text-[10px] text-muted hover:text-foreground hover:border-accent
                       transition-colors">
      Analyze traffic
    </button>
  </div>

  {/* Input area */}
  <div className="p-2 border-t border-border flex gap-2 items-end shrink-0">
    <textarea
      className="flex-1 bg-surface border border-border rounded px-2 py-1.5
                 text-xs text-foreground placeholder-muted resize-none
                 focus:outline-none focus:border-accent"
      style={{ maxHeight: "5rem" }}
    />
    <button className="p-1.5 rounded text-accent hover:bg-accent/10
                       disabled:opacity-30 transition-colors">
      <Send className="w-3.5 h-3.5" />
    </button>
  </div>
</aside>
```

### 6.7 Toast Notifications

NetScope uses its own lightweight `Toast.tsx` (no external library):

```tsx
// Usage — call toast() from anywhere
toast("Scan complete — 42 hosts found", "success")
toast("Connection refused at 192.168.1.1", "error")
toast("High latency detected", "warning")

// Appearance: fixed bottom-right, auto-dismiss 3s
// Colors: bg-surface, border border-border, left border 2px accent/success/danger/warning
```

### 6.8 Sidebar Tooltip

Tooltips appear on hover after a 400ms delay, positioned to the right of sidebar icons:

```css
.sidebar-tooltip {
  position: absolute;
  left: calc(100% + 8px);
  top: 50%;
  transform: translateY(-50%);
  background: rgb(var(--color-surface-active));
  border: 1px solid rgb(var(--color-border));
  border-radius: 4px;
  padding: 4px 8px;
  font-size: 12px;
  font-weight: 500;
  color: rgb(var(--color-foreground));
  white-space: nowrap;
  pointer-events: none;
  opacity: 0;
  transition: opacity 120ms ease;
  transition-delay: 400ms;  /* appears on .sidebar-item:hover */
}
```

---

## 7. Interaction & Animation

### Transitions

All interactive elements use `transition-colors` (150ms, default Tailwind). For the AI panel slide-in, use:

```css
transition: width 240ms cubic-bezier(0.16, 1, 0.3, 1);
```

### Capture Pulse

A live capture indicator pulses using:

```css
@keyframes capture-pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.4; }
}
.capture-pulse { animation: capture-pulse 1s ease-in-out infinite; }
```

### Network Topology Edge Animation

Animated dashed edges in the traffic map:

```css
@keyframes ns-flow {
  from { stroke-dashoffset: 24; }
  to { stroke-dashoffset: 0; }
}
.ns-flow-animated {
  stroke-dasharray: 4 4;
  animation: ns-flow 0.8s linear infinite;
}
```

### Row Hover

Packet rows use `filter: brightness(1.2)` on hover (applied to `[class^="row-"]` and `[class*=" row-"]` selectors) — this brightens both tinted and plain rows uniformly.

---

## 8. Protocol Visualization

### 8.1 Protocol Text & Background Colors

Used for badges and table cells. Available as Tailwind utilities:

```tsx
// Text color
<span className="text-protocol-HTTP">HTTP</span>
<span className="text-protocol-TLS">TLS</span>
<span className="text-protocol-DNS">DNS</span>
<span className="text-protocol-TCP">TCP</span>
<span className="text-protocol-UDP">UDP</span>
<span className="text-protocol-ICMP">ICMP</span>
<span className="text-protocol-ARP">ARP</span>
<span className="text-protocol-OTHER">OTHER</span>

// Background (15% opacity tint)
<div className="bg-protocol-HTTP" />  // also HTTPS
<div className="bg-protocol-DNS" />
// etc.
```

### 8.2 Wireshark-Style Row Tinting (Dark Mode Only)

In dark mode, full packet table rows get protocol-tinted backgrounds. These CSS classes are applied to `<tr>` elements:

| Class | Background | Text Color | Protocol |
|---|---|---|---|
| `.row-tcp` | `#131e2d` | `#c8d8f0` | TCP |
| `.row-tls` | `#161232` | `#d0c8f0` | TLS / SSL |
| `.row-dns` | `#0b1a12` | `#c0e8d0` | DNS |
| `.row-http` | `#101a28` | `#b8d8e8` | HTTP / HTTPS |
| `.row-udp` | `#131a2d` | `#c8c8f0` | UDP |
| `.row-arp` | `#14140a` | `#e8e8b8` | ARP |
| `.row-icmp` | `#131a1a` | `#b8e0e0` | ICMP |
| `.row-error` | `#270f0f` | `#f4b8b8` | Malformed / Error |
| `.row-warn` | `#22180a` | `#f4d8b8` | Warning |

**Important:** These classes are defined inside the `.dark {}` selector. They have **no effect in light mode**.

In **light mode**, use protocol badge pills instead of row tinting.

---

## 9. Tailwind Class Reference

### Tailwind Config Token Map

All design tokens are mapped in `frontend/tailwind.config.ts`:

```typescript
const v = (name: string) => `rgb(var(--color-${name}) / <alpha-value>)`;

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
  "muted-extra":    v("muted-extra"),
  accent:           v("accent"),
  success:          v("success"),
  warning:          v("warning"),
  danger:           v("danger"),
  purple:           v("purple"),
  // ... emphasis and subtle variants
  "protocol-http":  v("protocol-http"),
  "protocol-tls":   v("protocol-tls"),
  // ... all protocols
}
```

### Common Class Combos

```
Panel header:          bg-surface border-b border-border px-3 py-2 flex items-center gap-2
Data cell:             px-3 py-2 text-xs text-foreground font-mono
Secondary label:       text-xs text-muted
Disabled state:        opacity-50 cursor-not-allowed pointer-events-none
Focus ring:            focus:outline-none focus:border-accent
Active nav item:       text-accent bg-accent/10 [box-shadow:inset_-2px_0_0_rgb(var(--color-accent))]
Section divider:       border-t border-border
Scrollable container:  overflow-y-auto overflow-x-hidden
```

---

## 10. Do's and Don'ts

### ✅ DO

- Use `text-xs` (13px) as the standard body text size
- Use `text-foreground` for primary content, `text-muted` for labels, `text-muted-dim` for timestamps and placeholders
- Use `bg-surface` / `bg-background` for semantic contrast — never `bg-gray-100`
- Use `border-border` for all borders — never `border-gray-200` or `border-black/10`
- Use `transition-colors` on every interactive element
- Use `font-mono tabular-nums` for IP addresses, port numbers, timestamps
- Use 4px border radius (`rounded`) as the default; `rounded-md` (6px) is the maximum for most components
- Apply `.dark` class to `<html>` element to activate dark theme
- Use `text-accent` to highlight active/focused state, not custom blue values
- Use `text-protocol-{NAME}` and `bg-protocol-{NAME}` for protocol indicators

### ❌ DON'T

- Don't use pure `#000000` for text — use `text-foreground` (`#1c1c1e` light, `#e2e8f0` dark)
- Don't use `rounded-full` or `rounded-xl` — max is `rounded-md`
- Don't add `box-shadow` to cards or panels — use tonal surface shifts instead
- Don't use hardcoded hex colors in components — always use CSS variables via Tailwind tokens
- Don't use `border-b-2` for table row dividers — use `border-b border-border` (1px)
- Don't use `text-sm` (14px) as the base — it breaks the compact density
- Don't use external toast/notification libraries — use the built-in `Toast.tsx`
- Don't use CSS Grid in components — all layout is Flexbox
- Don't use large spacing (`p-6`, `gap-8`) inside data-dense areas
- Don't add drop shadows to popovers/tooltips — use `bg-surface-active border border-border`
- Don't use the Wireshark row classes (`.row-tcp` etc.) in light mode — they are dark-only

---

## Appendix A — Complete CSS Variable Reference

```css
/* Light mode (:root) */
--color-background:          249 249 254;   /* #f9f9fe */
--color-surface:             240 240 245;   /* #f0f0f5 */
--color-surface-hover:       226 226 232;
--color-surface-active:      208 208 216;
--color-border:              210 210 216;
--color-border-subtle:       226 226 232;
--color-foreground:          28 28 30;      /* #1c1c1e — Apple system label */
--color-muted:               99 108 118;   /* #636c76 */
--color-muted-dim:           152 160 168;  /* #98a0a8 */
--color-accent:              0 102 255;    /* #0066ff */
--color-success:             36 174 75;    /* #24ae4b */
--color-warning:             215 125 0;    /* #d77d00 */
--color-danger:              220 48 38;    /* #dc3026 */
--color-purple:              149 58 196;   /* #953ac4 */

/* Dark mode (.dark) */
--color-background:          10 10 11;     /* #0a0a0b */
--color-surface:             13 17 23;     /* #0d1117 — GitHub dark */
--color-surface-hover:       22 27 34;
--color-surface-active:      28 33 40;
--color-border:              33 38 45;     /* #21262d — GitHub dark border */
--color-border-subtle:       48 54 61;
--color-foreground:          226 232 240;  /* #e2e8f0 */
--color-muted:               139 148 158;  /* #8b949e — GitHub muted */
--color-muted-dim:           74 85 104;
--color-accent:              88 166 255;   /* #58a6ff — GitHub blue */
--color-success:             63 185 80;    /* #3fb950 */
--color-warning:             210 153 34;   /* #d29922 */
--color-danger:              248 81 73;    /* #f85149 */
```

---

## Appendix B — File Structure

```
frontend/src/
├── index.css                  ← All CSS tokens + theme definitions
├── App.tsx                    ← Root component, theme toggle logic
├── components/
│   ├── Dashboard.tsx          ← Main layout, sidebar, tab routing
│   ├── RightPanel.tsx         ← AI chat panel
│   ├── NetworkTools.tsx       ← All network diagnostic tools
│   ├── PacketCapture.tsx      ← Wireshark-style packet table
│   ├── StatusPanel.tsx        ← Host status monitoring
│   ├── Toast.tsx              ← Lightweight toast system
│   ├── TokenCounter.tsx       ← LLM token usage display
│   └── ...
├── lib/
│   └── api.ts                 ← Axios client + WebSocket factory
└── store/
    └── useStore.ts            ← Zustand global state
```

---

*Generated: 2026-04-05 | Stitch project: `7103266401353209945` (NetScope Desktop Apple UI)*
