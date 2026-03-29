# Netscope Desktop UI Redesign — Design Spec

**Date:** 2026-03-26
**Status:** Approved
**Goal:** Consolidate the scattered 12-tab sidebar into a focused, Wireshark-faithful layout with a persistent chat column and icon rail navigation.

---

## 1. Problem Statement

The current UI has three structural problems:

1. **12 navigation tabs** across three sections (Capture, Tools, System) overwhelm users and bury critical features behind unrelated admin views.
2. **Chat is a separate full tab** — switching to Chat loses sight of the packet table, breaking the analysis workflow. Users cannot see packets and ask questions simultaneously.
3. **Analysis is scattered** — Insights live inside the Packets tab, but Analysis (ExpertTools), Traffic Map, and the new Deep/Quick modes each live in different places with no unified entry point.

---

## 2. Approved Design

### 2.1 Overall Shell

```
┌─────┬──────────────────────────────────────┬─────────────────────┐
│     │  Toolbar (Start/Stop/Interface/       │                     │
│ 5   │  Import/Captures/LLM/Settings)       │  Right Panel        │
│     ├──────────────────────────────────────┤  (320px fixed)      │
│ i   │  Filter bar (Wireshark display filter)│                     │
│ c   ├──────────────────────────────────────┤  ┌────────────────┐ │
│ o   │                                      │  │ Chat│Quick│Deep│ │
│ n   │  Packet Table (Wireshark-style)       │  ├────────────────┤ │
│     │                                      │  │ Analysis strip │ │
│ r   │  No. │ Time │ Src │ Dst │ Proto │ .. │  │  (collapsible) │ │
│ a   │                                      │  ├────────────────┤ │
│ i   │                                      │  │ Chat messages  │ │
│ l   ├──────────────────────────────────────┤  ├────────────────┤ │
│     │  Status bar                          │  │ Prompt chips   │ │
│ 52px│                                      │  │ Input + Send   │ │
└─────┴──────────────────────────────────────┴─────────────────────┘
```

### 2.2 Left Icon Rail (52px)

Five icons, SVG, with hover tooltips. Active icon gets a left accent bar and highlighted background.

| Position | Icon | View |
|----------|------|------|
| 1 | Activity waveform | Capture (default) |
| 2 | Search/magnifier | Analysis (ExpertTools + Deep mode) |
| 3 | Share/graph | Traffic Map |
| 4 | Building/server | Protocols (Modbus, future ICS tools) |
| — | spacer | — |
| 5 (bottom) | Gear | Settings flyout |

**Settings flyout** (slide-in panel, not a nav tab): Knowledge Base (RAG), Channels, Status, Scheduler, LLM config, theme toggle.

### 2.3 Capture View (center, flex-1)

**Toolbar** (single row):
- Left: `▶ Start` (primary blue), `⬛ Stop` (danger), interface `<select>`
- Live indicator: pulsing green dot + "LIVE" text (hidden when not capturing)
- Right: `📥 Import` (ghost), `💾 Captures` (ghost), divider, LLM badge, ⚙ icon

**Filter bar** (below toolbar):
- Full-width display filter input (Wireshark syntax, monospace font, placeholder: `Apply a display filter …`)
- Active filter tags (removable chips)
- Clear button

**Packet Table** — Wireshark-faithful:
- Columns: `No. · Time · Source · Destination · Protocol · Length · Info`
- Monospace font throughout (`Consolas`, `JetBrains Mono`, fallback `monospace`)
- Row color coding by protocol (matches Wireshark defaults):
  - TCP: `#1a2535` / text `#c8d8f0`
  - TLS/SSL: `#1e1835` / text `#d0c8f0`
  - DNS: `#0f2018` / text `#c0e8d0`
  - HTTP: `#162030` / text `#b8d8e8`
  - UDP: `#1a2035` / text `#c8c8f0`
  - ARP: `#1a1a0f` / text `#e8e8b8`
  - ICMP: `#1a2020` / text `#b8e0e0`
  - TCP errors (retransmission, RST, OOO): `#2d1515` / text `#f4b8b8`
  - TCP warnings (zero-window, dup ACK): `#2a1e10` / text `#f4d8b8`
- Click row → selected highlight (blue outline)
- Double-click row → packet detail inspector (future — out of scope for this redesign)

**Status bar** (below table):
- Left: `N packets · M retransmissions · X KB captured`
- Right: `Displaying N of N packets`

### 2.4 Right Panel (320px)

**Sub-tabs** (header row):
- `💬 Chat` | `⚡ Quick` | `🔬 Deep`
- All three persist in the same column — no route change, no tab switch

**Analysis strip** (collapsible, below sub-tabs):
- Collapsed state: single header row "✓ Deep Analysis · Xs ago" + colored metric pills
  - Pills: retransmit count (red), zero-windows (amber), bottleneck (purple), RTT (green), RSTs (blue)
  - Click pill → pre-fills chat input with relevant question
- Expanded state: full Deep mode MetricCards (TCP Health, Latency, Streams, Expert Info, IO Timeline, Narrative) — same cards as currently in InsightPanel
- Hidden when no deep analysis has run

**Chat thread** (scrollable, flex-1):
- Bot messages: dark card, left blue border, `⬡ NETSCOPE` label, markdown rendered
- User messages: blue-tinted right-aligned bubble
- `analysisContext` injected into every message automatically

**Suggested prompt chips** (above input):
- Static chips + dynamic chips generated from latest analysis findings ("Why so many RSTs?", "Follow stream 0", etc.)
- Click chip → fills input

**Input area**:
- Textarea (auto-resize, 1–5 rows), send button (↑)
- Paperclip button for pcap upload (already implemented in ChatBox)

---

## 3. Navigation Changes

### Removed from sidebar
All 12 current sidebar tabs are removed.

### Mapped to new locations

| Old tab | New location |
|---------|-------------|
| Packets & Insights | Capture view (default, icon 1) |
| Chat | Right panel (permanent) |
| Analysis (ExpertTools) | Analysis view (icon 2) |
| Traffic Map | Traffic Map view (icon 3) |
| Modbus | Protocols view (icon 4) |
| Import PCAP | Toolbar button in Capture view |
| Captures | Toolbar button in Capture view |
| Knowledge Base (RAG) | Settings flyout |
| Channels | Settings flyout |
| Status | Settings flyout |
| Scheduler | Settings flyout |
| Net Tools | Settings flyout (or inline in Analysis view — TBD) |

### InsightPanel consolidation
The existing `InsightPanel` (currently in `PacketsAndInsights` as a 380px sidebar) is **retired as a standalone sidebar**. Its functionality splits:
- Quick/Deep mode trigger buttons → right panel sub-tabs
- Deep mode metric cards → analysis strip (expanded state)
- Insight history → chat thread (insights posted as bot messages)

---

## 4. Component Architecture

### New / heavily modified components

**`Dashboard.tsx`** — Remove `NAV_SECTIONS` / sidebar tabs. Add `IconRail`. Route content area based on `activeView` (5 values: `capture | analysis | trafficmap | protocols | settings`). Keep existing `<ChatBox>` but move it into `RightPanel`.

**`IconRail.tsx`** (new) — 52px rail with SVG icons, active state, tooltips. Props: `activeView`, `onViewChange`.

**`RightPanel.tsx`** (new) — 320px column containing sub-tab header, `AnalysisStrip`, `ChatThread`, `PromptChips`, `ChatInput`. Replaces the role of the current standalone `ChatBox` tab.

**`AnalysisStrip.tsx`** (new) — Reads `analysisReport` from Zustand. Collapsed/expanded toggle. Renders pills (collapsed) or MetricCards (expanded).

**`PacketsAndInsights.tsx`** — Simplify: remove right InsightPanel sidebar. Packet table takes full width.

**`InsightPanel.tsx`** — Retire the component. Logic moves into `RightPanel` (sub-tabs) and `AnalysisStrip`.

**`PacketTable.tsx`** — Add Wireshark-accurate row color coding based on `protocol` and `details` fields (retransmission, zero_window flags). Row colors defined as a lookup table matching section 2.3.

### Unchanged components
`FilterBar`, `ExpertTools`, `TrafficMap`, `ModbusPanel`, `RAGPanel`, `ChannelsPanel`, `StatusPanel`, `SchedulerPanel`, `NetworkTools`, `CaptureManager`, `PcapUpload` — all retained, just re-routed.

---

## 5. State Changes

### Zustand store additions
```typescript
activeView: 'capture' | 'analysis' | 'trafficmap' | 'protocols' | 'settings';
setActiveView: (v: ActiveView) => void;
rightPanelTab: 'chat' | 'quick' | 'deep';
setRightPanelTab: (t: RightPanelTab) => void;
analysisStripExpanded: boolean;
setAnalysisStripExpanded: (v: boolean) => void;
```

### Removed store fields
`activeTab` (replaced by `activeView`) — migration: map existing `activeTab` values to `activeView`.

---

## 6. Packet Row Color Lookup

The `PacketTable` component uses a `getRowClass(packet)` function:

```typescript
function getRowClass(pkt: Packet): string {
  const d = pkt.details ?? {};
  if (d.tcp_retransmission || d.tcp_out_of_order || pkt.protocol === 'TCP' && pkt.info?.includes('[RST]'))
    return 'row-error';
  if (d.tcp_zero_window || d.tcp_dup_ack)
    return 'row-warn';
  switch (pkt.protocol) {
    case 'TLSv1.2': case 'TLSv1.3': case 'SSL': return 'row-tls';
    case 'DNS': case 'MDNS': return 'row-dns';
    case 'HTTP': case 'HTTP2': return 'row-http';
    case 'UDP': return 'row-udp';
    case 'ARP': return 'row-arp';
    case 'ICMP': case 'ICMPv6': return 'row-icmp';
    default: return 'row-tcp';
  }
}
```

---

## 7. Files Changed

**New files:**
- `frontend/src/components/IconRail.tsx`
- `frontend/src/components/RightPanel.tsx`
- `frontend/src/components/AnalysisStrip.tsx`

**Modified files:**
- `frontend/src/components/Dashboard.tsx` — replace sidebar with IconRail + RightPanel
- `frontend/src/components/PacketsAndInsights.tsx` — remove InsightPanel sidebar
- `frontend/src/components/PacketTable.tsx` — add Wireshark row color coding
- `frontend/src/store/useStore.ts` — add `activeView`, `rightPanelTab`, `analysisStripExpanded`; keep `activeTab` as alias during migration

**Retired (kept but no longer rendered as top-level):**
- `frontend/src/components/InsightPanel.tsx` — logic absorbed into RightPanel + AnalysisStrip

---

## 8. Out of Scope

- Packet detail inspector (double-click row) — future task
- Resizable right panel — future task
- Column reordering in packet table — future task
- Settings flyout panel implementation — addressed in a follow-up spec
