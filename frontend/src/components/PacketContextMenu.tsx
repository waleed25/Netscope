/**
 * PacketContextMenu — Wireshark-accurate right-click context menu for the
 * packet list.  Mirrors Wireshark's menu sections in order:
 *
 *   Mark / Ignore
 *   Apply as Filter  (sub-menu)
 *   Prepare a Filter (sub-menu)
 *   Conversation Filter (sub-menu)
 *   Follow           (TCP / UDP / TLS Stream)
 *   ── separator ──
 *   Copy             (sub-menu)
 *   ── separator ──
 *   Decode As…
 *   Show Packet in New Window
 *
 * Actions that require backend state (Decode As, Stream re-assembly) are
 * shown but disabled with a tooltip explaining the limitation.
 */

import { useEffect, useRef, useState } from "react";
import {
  ChevronRight, Check, Minus, Copy, Filter, Link2,
  Eye, EyeOff, RefreshCcw, ExternalLink, ArrowRight,
} from "lucide-react";
import type { Packet } from "../store/useStore";

// ── Types ─────────────────────────────────────────────────────────────────────

export interface ContextMenuState {
  x: number;
  y: number;
  pkt: Packet;
}

interface Props {
  state: ContextMenuState;
  markedIds: Set<number>;
  ignoredIds: Set<number>;
  onClose: () => void;
  onApplyFilter: (filter: string) => void;
  onMarkToggle: (id: number) => void;
  onIgnoreToggle: (id: number) => void;
  onFollowStream: (pkt: Packet, proto: "tcp" | "udp") => void;
}

// ── Constants ─────────────────────────────────────────────────────────────────

const MENU_W  = 240;
const SUB_W   = 220;
const ITEM_H  = 24;
const BG      = "#1c2128";
const BG_HOVERED = "#2d333b";
const BORDER  = "#444c56";
const TEXT    = "#cdd9e5";
const MUTED   = "#768390";
const ACCENT  = "#539bf5";

const menuStyle: React.CSSProperties = {
  position: "fixed",
  width: MENU_W,
  background: BG,
  border: `1px solid ${BORDER}`,
  borderRadius: 6,
  boxShadow: "0 8px 24px rgba(0,0,0,0.5)",
  zIndex: 9999,
  padding: "3px 0",
  fontFamily: "var(--font-mono, 'JetBrains Mono', monospace)",
  fontSize: 12,
  userSelect: "none",
};

// ── Menu item helpers ─────────────────────────────────────────────────────────

interface ItemProps {
  label: string;
  icon?: React.ReactNode;
  shortcut?: string;
  checked?: boolean;
  disabled?: boolean;
  danger?: boolean;
  hasSubmenu?: boolean;
  onClick?: () => void;
  onMouseEnter?: () => void;
  onMouseLeave?: () => void;
}

function MenuItem({
  label, icon, shortcut, checked, disabled, danger, hasSubmenu, onClick, onMouseEnter, onMouseLeave,
}: ItemProps) {
  const [hovered, setHovered] = useState(false);
  return (
    <div
      role="menuitem"
      aria-disabled={disabled}
      onClick={disabled ? undefined : onClick}
      onMouseEnter={() => { setHovered(true); onMouseEnter?.(); }}
      onMouseLeave={() => { setHovered(false); onMouseLeave?.(); }}
      style={{
        display: "flex",
        alignItems: "center",
        gap: 6,
        height: ITEM_H,
        padding: "0 8px",
        cursor: disabled ? "default" : "pointer",
        background: hovered && !disabled ? BG_HOVERED : "transparent",
        color: disabled ? MUTED : danger ? "#e5534b" : TEXT,
        transition: "background 60ms",
      }}
    >
      {/* Check / icon slot */}
      <span style={{ width: 16, display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0 }}>
        {checked === true  && <Check  className="w-3 h-3" style={{ color: ACCENT }} />}
        {checked === false && <Minus  className="w-3 h-3" style={{ color: MUTED }} />}
        {checked == null   && icon && <span style={{ color: hovered ? ACCENT : MUTED }}>{icon}</span>}
      </span>

      <span style={{ flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
        {label}
      </span>

      {shortcut && (
        <span style={{ color: MUTED, fontSize: 10, flexShrink: 0 }}>{shortcut}</span>
      )}
      {hasSubmenu && (
        <ChevronRight className="w-3 h-3 shrink-0" style={{ color: MUTED }} />
      )}
    </div>
  );
}

function Separator() {
  return <div style={{ height: 1, background: BORDER, margin: "3px 0" }} />;
}

function SectionLabel({ label }: { label: string }) {
  return (
    <div style={{ padding: "2px 12px", fontSize: 10, color: MUTED, textTransform: "uppercase", letterSpacing: "0.08em" }}>
      {label}
    </div>
  );
}

// ── Sub-menu wrapper ──────────────────────────────────────────────────────────

interface SubMenuProps {
  label: string;
  icon?: React.ReactNode;
  disabled?: boolean;
  parentX: number;
  parentY: number;   // top of the parent item in viewport coords
  parentRight: number; // right edge of parent menu
  children: React.ReactNode;
}

function SubMenu({ label, icon, disabled, parentX, parentY, parentRight, children }: SubMenuProps) {
  const [open, setOpen] = useState(false);
  const [hovered, setHovered] = useState(false);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const openSub = () => {
    if (timerRef.current) clearTimeout(timerRef.current);
    setOpen(true);
  };
  const closeSub = () => {
    timerRef.current = setTimeout(() => setOpen(false), 120);
  };

  // Position sub-menu: prefer right side, flip left if near edge
  const subX = parentRight + 2 > window.innerWidth - SUB_W
    ? parentX - SUB_W - 2
    : parentRight + 2;
  const subY = Math.min(parentY, window.innerHeight - 300);

  return (
    <div
      onMouseEnter={() => { setHovered(true); if (!disabled) openSub(); }}
      onMouseLeave={() => { setHovered(false); closeSub(); }}
    >
      <div
        style={{
          display: "flex", alignItems: "center", gap: 6,
          height: ITEM_H, padding: "0 8px",
          cursor: disabled ? "default" : "pointer",
          background: (hovered || open) && !disabled ? BG_HOVERED : "transparent",
          color: disabled ? MUTED : TEXT,
        }}
      >
        <span style={{ width: 16, display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0 }}>
          {icon && <span style={{ color: hovered ? ACCENT : MUTED }}>{icon}</span>}
        </span>
        <span style={{ flex: 1 }}>{label}</span>
        <ChevronRight className="w-3 h-3 shrink-0" style={{ color: MUTED }} />
      </div>

      {open && !disabled && (
        <div
          onMouseEnter={openSub}
          onMouseLeave={closeSub}
          style={{
            ...menuStyle,
            left: subX,
            top: subY,
            width: SUB_W,
          }}
        >
          {children}
        </div>
      )}
    </div>
  );
}

// ── Main context menu ─────────────────────────────────────────────────────────

export function PacketContextMenu({
  state, markedIds, ignoredIds, onClose,
  onApplyFilter, onMarkToggle, onIgnoreToggle, onFollowStream,
}: Props) {
  const { x, y, pkt } = state;
  const menuRef = useRef<HTMLDivElement>(null);
  const [copied, setCopied] = useState("");

  // Position: keep within viewport — open below if room, flip above if not,
  // clamp to top edge if neither fully fits.
  const ESTIMATED_H = 340;
  const menuX = x + MENU_W > window.innerWidth  ? x - MENU_W : x;
  const menuY = (() => {
    if (y + ESTIMATED_H <= window.innerHeight) return y;           // fits below
    if (y >= ESTIMATED_H)                      return y - ESTIMATED_H; // fits above
    return Math.max(0, window.innerHeight - ESTIMATED_H);          // clamp
  })();

  // Close on outside click or Escape
  useEffect(() => {
    const onDown = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) onClose();
    };
    const onKey  = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [onClose]);

  const copy = (text: string, label: string) => {
    navigator.clipboard.writeText(text).catch(() => {});
    setCopied(label);
    setTimeout(() => { setCopied(""); onClose(); }, 600);
  };

  const applyFilter = (f: string) => { onApplyFilter(f); onClose(); };

  const isMarked   = markedIds.has(pkt.id);
  const isIgnored  = ignoredIds.has(pkt.id);
  const protoLow   = (pkt.protocol ?? "").toLowerCase();
  const isTCP      = protoLow === "tcp"  || pkt.layers?.some(l => l.toUpperCase() === "TCP");
  const isUDP      = protoLow === "udp"  || pkt.layers?.some(l => l.toUpperCase() === "UDP");
  const isTLS      = protoLow.includes("tls") || protoLow.includes("ssl") ||
                     pkt.layers?.some(l => ["TLS","SSL"].includes(l.toUpperCase()));

  const srcPort = pkt.src_port && pkt.src_port !== "-" && pkt.src_port !== "0" ? pkt.src_port : null;
  const dstPort = pkt.dst_port && pkt.dst_port !== "-" && pkt.dst_port !== "0" ? pkt.dst_port : null;
  const portKey = isTCP ? "tcp.port" : "udp.port";

  const menuRight = menuX + MENU_W;

  return (
    <div ref={menuRef} style={{ ...menuStyle, left: menuX, top: menuY }}>

      {/* ── Section 1: Mark / Ignore ────────────────────────────────────────── */}
      <MenuItem
        label={isMarked ? "Unmark Packet" : "Mark Packet"}
        icon={<Check className="w-3 h-3" />}
        checked={isMarked}
        onClick={() => { onMarkToggle(pkt.id); onClose(); }}
      />
      <MenuItem
        label={isIgnored ? "Unignore Packet" : "Ignore Packet"}
        icon={<EyeOff className="w-3 h-3" />}
        checked={isIgnored}
        onClick={() => { onIgnoreToggle(pkt.id); onClose(); }}
      />

      <Separator />

      {/* ── Section 2: Apply as Filter ──────────────────────────────────────── */}
      <SubMenu
        label="Apply as Filter"
        icon={<Filter className="w-3 h-3" />}
        parentX={menuX}
        parentRight={menuRight}
        parentY={menuY + ITEM_H * 3 + 8}
      >
        <SectionLabel label="Source" />
        <MenuItem label={`ip.src == ${pkt.src_ip}`}
          onClick={() => applyFilter(`ip.src == ${pkt.src_ip}`)} />
        {srcPort && (
          <MenuItem label={`${portKey} == ${srcPort}`}
            onClick={() => applyFilter(`${portKey} == ${srcPort}`)} />
        )}
        <Separator />
        <SectionLabel label="Destination" />
        <MenuItem label={`ip.dst == ${pkt.dst_ip}`}
          onClick={() => applyFilter(`ip.dst == ${pkt.dst_ip}`)} />
        {dstPort && (
          <MenuItem label={`${portKey} == ${dstPort}`}
            onClick={() => applyFilter(`${portKey} == ${dstPort}`)} />
        )}
        <Separator />
        <SectionLabel label="Either" />
        <MenuItem label={`ip.addr == ${pkt.src_ip}`}
          onClick={() => applyFilter(`ip.addr == ${pkt.src_ip}`)} />
        <MenuItem label={`ip.addr == ${pkt.dst_ip}`}
          onClick={() => applyFilter(`ip.addr == ${pkt.dst_ip}`)} />
        <Separator />
        <SectionLabel label="Exclude" />
        <MenuItem label={`!(ip.addr == ${pkt.src_ip})`}
          onClick={() => applyFilter(`!(ip.addr == ${pkt.src_ip})`)} />
        <MenuItem label={`!(${protoLow || "ip"})`}
          onClick={() => applyFilter(`!(${protoLow || "ip"})`)} />
      </SubMenu>

      {/* ── Section 3: Prepare a Filter ─────────────────────────────────────── */}
      <SubMenu
        label="Prepare a Filter"
        icon={<ArrowRight className="w-3 h-3" />}
        parentX={menuX}
        parentRight={menuRight}
        parentY={menuY + ITEM_H * 4 + 8}
      >
        <SectionLabel label="Prepare (does not apply)" />
        <MenuItem label={`ip.src == ${pkt.src_ip}`}
          onClick={() => { onApplyFilter(`ip.src == ${pkt.src_ip}`); onClose(); }} />
        <MenuItem label={`ip.dst == ${pkt.dst_ip}`}
          onClick={() => { onApplyFilter(`ip.dst == ${pkt.dst_ip}`); onClose(); }} />
        <MenuItem label={`ip.addr == ${pkt.src_ip} && ip.addr == ${pkt.dst_ip}`}
          onClick={() => { onApplyFilter(`ip.addr == ${pkt.src_ip} && ip.addr == ${pkt.dst_ip}`); onClose(); }} />
        {pkt.protocol && (
          <MenuItem label={protoLow}
            onClick={() => { onApplyFilter(protoLow); onClose(); }} />
        )}
      </SubMenu>

      {/* ── Section 4: Conversation Filter ──────────────────────────────────── */}
      <SubMenu
        label="Conversation Filter"
        icon={<Link2 className="w-3 h-3" />}
        parentX={menuX}
        parentRight={menuRight}
        parentY={menuY + ITEM_H * 5 + 8}
      >
        <MenuItem
          label="IPv4 Conversation"
          onClick={() => applyFilter(`(ip.addr == ${pkt.src_ip} && ip.addr == ${pkt.dst_ip})`)}
        />
        {isTCP && srcPort && dstPort && (
          <MenuItem
            label="TCP Conversation"
            onClick={() => applyFilter(
              `(ip.addr == ${pkt.src_ip} && ip.addr == ${pkt.dst_ip} && tcp.port == ${srcPort} && tcp.port == ${dstPort})`
            )}
          />
        )}
        {isUDP && srcPort && dstPort && (
          <MenuItem
            label="UDP Conversation"
            onClick={() => applyFilter(
              `(ip.addr == ${pkt.src_ip} && ip.addr == ${pkt.dst_ip} && udp.port == ${srcPort} && udp.port == ${dstPort})`
            )}
          />
        )}
      </SubMenu>

      <Separator />

      {/* ── Section 5: Follow Stream ─────────────────────────────────────────── */}
      <MenuItem
        label="Follow TCP Stream"
        icon={<RefreshCcw className="w-3 h-3" />}
        disabled={!isTCP}
        onClick={() => { onFollowStream(pkt, "tcp"); onClose(); }}
      />
      <MenuItem
        label="Follow UDP Stream"
        icon={<RefreshCcw className="w-3 h-3" />}
        disabled={!isUDP}
        onClick={() => { onFollowStream(pkt, "udp"); onClose(); }}
      />
      <MenuItem
        label="Follow TLS Stream"
        icon={<RefreshCcw className="w-3 h-3" />}
        disabled={!isTLS}
        onClick={() => { onFollowStream(pkt, "tcp"); onClose(); }}
      />

      <Separator />

      {/* ── Section 6: Copy ──────────────────────────────────────────────────── */}
      <SubMenu
        label={copied ? `✓ Copied!` : "Copy"}
        icon={<Copy className="w-3 h-3" />}
        parentX={menuX}
        parentRight={menuRight}
        parentY={menuY + ITEM_H * 9 + 14}
      >
        <MenuItem label="Summary (one-line)"
          onClick={() => copy(
            `${pkt.id}\t${new Date(pkt.timestamp * 1000).toISOString()}\t${pkt.src_ip}:${pkt.src_port}\t${pkt.dst_ip}:${pkt.dst_port}\t${pkt.protocol}\t${pkt.length}\t${pkt.info}`,
            "Summary"
          )} />
        <MenuItem label="Source IP"
          onClick={() => copy(pkt.src_ip, "Source IP")} />
        <MenuItem label="Destination IP"
          onClick={() => copy(pkt.dst_ip, "Destination IP")} />
        {srcPort && (
          <MenuItem label="Source Port"
            onClick={() => copy(pkt.src_port, "Source Port")} />
        )}
        {dstPort && (
          <MenuItem label="Destination Port"
            onClick={() => copy(pkt.dst_port, "Destination Port")} />
        )}
        <MenuItem label="Info column text"
          onClick={() => copy(pkt.info ?? "", "Info")} />
        <Separator />
        <MenuItem label="as JSON"
          onClick={() => copy(JSON.stringify(pkt, null, 2), "JSON")} />
        <MenuItem label="as CSV row"
          onClick={() => copy(
            [pkt.id, new Date(pkt.timestamp * 1000).toISOString(),
             `${pkt.src_ip}:${pkt.src_port}`, `${pkt.dst_ip}:${pkt.dst_port}`,
             pkt.protocol, pkt.length, `"${(pkt.info ?? "").replace(/"/g, '""')}"`].join(","),
            "CSV"
          )} />
        <MenuItem label="All visible fields"
          onClick={() => copy(
            Object.entries(pkt.details ?? {})
              .filter(([, v]) => v)
              .map(([k, v]) => `${k}: ${v}`)
              .join("\n"),
            "Fields"
          )} />
        <MenuItem label="Hex stream (IP+Transport)"
          onClick={() => {
            // Build hex string from reconstructed bytes
            const parts: string[] = [];
            if (pkt.src_ip) parts.push(...pkt.src_ip.split(".").map(n => parseInt(n).toString(16).padStart(2, "0")));
            if (pkt.dst_ip) parts.push(...pkt.dst_ip.split(".").map(n => parseInt(n).toString(16).padStart(2, "0")));
            if (pkt.src_port) {
              const p = parseInt(pkt.src_port);
              if (!isNaN(p)) parts.push(((p >> 8) & 0xff).toString(16).padStart(2, "0"), (p & 0xff).toString(16).padStart(2, "0"));
            }
            if (pkt.dst_port) {
              const p = parseInt(pkt.dst_port);
              if (!isNaN(p)) parts.push(((p >> 8) & 0xff).toString(16).padStart(2, "0"), (p & 0xff).toString(16).padStart(2, "0"));
            }
            copy(parts.join(""), "Hex");
          }} />
      </SubMenu>

      <Separator />

      {/* ── Section 7: Decode / View ─────────────────────────────────────────── */}
      <MenuItem
        label="Decode As…"
        icon={<Eye className="w-3 h-3" />}
        disabled
      />
      <MenuItem
        label="Show Packet in New Window"
        icon={<ExternalLink className="w-3 h-3" />}
        onClick={() => {
          const win = window.open("", "_blank", "width=700,height=500");
          if (!win) return;
          const tree = Object.entries(pkt.details ?? {})
            .filter(([, v]) => v)
            .map(([k, v]) => `  <tr><td style="color:#8b949e;padding:1px 8px;font-family:monospace;font-size:12px">${k}</td><td style="color:#e6edf3;padding:1px 8px;font-family:monospace;font-size:12px">${v}</td></tr>`)
            .join("");
          win.document.write(`<!DOCTYPE html><html><head><title>Packet #${pkt.id}</title>
            <style>body{background:#0d1117;color:#e6edf3;font-family:monospace;font-size:12px;margin:12px}
            th{color:#8b949e;text-align:left;padding:2px 8px;border-bottom:1px solid #30363d}</style></head>
            <body>
            <h3 style="color:#58a6ff;margin:0 0 8px">Packet #${pkt.id} — ${pkt.protocol} — ${pkt.length} bytes</h3>
            <p style="color:#8b949e;margin:0 0 8px">${new Date(pkt.timestamp * 1000).toISOString()}<br>
            ${pkt.src_ip}:${pkt.src_port} → ${pkt.dst_ip}:${pkt.dst_port}</p>
            <p style="color:#c9d1d9;margin:0 0 8px">${pkt.info ?? ""}</p>
            <table><thead><tr><th>Field</th><th>Value</th></tr></thead><tbody>${tree}</tbody></table>
            </body></html>`);
          win.document.close();
          onClose();
        }}
      />
    </div>
  );
}
