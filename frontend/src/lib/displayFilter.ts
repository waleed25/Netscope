/**
 * displayFilter.ts
 *
 * Client-side Wireshark display-filter interpreter.
 * Parses common display filter syntax and evaluates it against in-memory
 * Packet objects — no tshark or backend required.
 *
 * Supported syntax:
 *   tcp / udp / dns / http / tls / arp / icmp / …    (bare protocol name)
 *   ip.src == 1.2.3.4          ip.dst != 1.2.3.4
 *   ip.addr == 1.2.3.4         (matches src OR dst)
 *   tcp.port == 443            (matches src OR dst port)
 *   tcp.srcport == 80          tcp.dstport == 443
 *   udp.port == 53
 *   frame.len > 100            frame.len <= 1500
 *   frame.number == 42
 *   ip.src contains "192.168"
 *   !expr  /  not expr
 *   A && B  /  A and B
 *   A || B  /  A or B
 *   (grouped sub-expressions)
 */

import type { Packet } from "../store/useStore";

// ── Tokeniser ──────────────────────────────────────────────────────────────────

type TokKind =
  | "IDENT"   // identifier or dotted field name: ip.src, tcp.port, tcp
  | "VALUE"   // literal: 1.2.3.4, 443, "string"
  | "OP"      // ==  !=  >  <  >=  <=  contains  matches
  | "AND"     // &&  and
  | "OR"      // ||  or
  | "NOT"     // !  not
  | "LPAREN"
  | "RPAREN";

interface Tok {
  kind: TokKind;
  text: string;
}

function tokenize(src: string): Tok[] {
  const toks: Tok[] = [];
  let i = 0;

  while (i < src.length) {
    // Whitespace
    if (/\s/.test(src[i])) { i++; continue; }

    // Parens
    if (src[i] === "(") { toks.push({ kind: "LPAREN", text: "(" }); i++; continue; }
    if (src[i] === ")") { toks.push({ kind: "RPAREN", text: ")" }); i++; continue; }

    // Two-char operators first
    const two = src.slice(i, i + 2);
    if (two === "==") { toks.push({ kind: "OP",  text: "==" }); i += 2; continue; }
    if (two === "!=") { toks.push({ kind: "OP",  text: "!=" }); i += 2; continue; }
    if (two === ">=") { toks.push({ kind: "OP",  text: ">=" }); i += 2; continue; }
    if (two === "<=") { toks.push({ kind: "OP",  text: "<=" }); i += 2; continue; }
    if (two === "&&") { toks.push({ kind: "AND", text: "&&" }); i += 2; continue; }
    if (two === "||") { toks.push({ kind: "OR",  text: "||" }); i += 2; continue; }

    // Single-char operators
    if (src[i] === ">") { toks.push({ kind: "OP",  text: ">" }); i++; continue; }
    if (src[i] === "<") { toks.push({ kind: "OP",  text: "<" }); i++; continue; }
    if (src[i] === "!") { toks.push({ kind: "NOT", text: "!" }); i++; continue; }

    // Quoted string
    if (src[i] === '"' || src[i] === "'") {
      const q = src[i];
      let j = i + 1;
      while (j < src.length && src[j] !== q) j++;
      toks.push({ kind: "VALUE", text: src.slice(i + 1, j) });
      i = j + 1;
      continue;
    }

    // Identifier / keyword / number / IP / dotted field
    if (/[a-zA-Z0-9._\-/]/.test(src[i])) {
      let j = i;
      while (j < src.length && /[a-zA-Z0-9._\-/]/.test(src[j])) j++;
      const text = src.slice(i, j);
      const low = text.toLowerCase();
      if      (low === "and")                   toks.push({ kind: "AND", text });
      else if (low === "or")                    toks.push({ kind: "OR",  text });
      else if (low === "not")                   toks.push({ kind: "NOT", text });
      else if (low === "contains" || low === "matches") toks.push({ kind: "OP", text: low });
      else                                      toks.push({ kind: "IDENT", text });
      i = j;
      continue;
    }

    i++; // skip unrecognised char
  }

  return toks;
}

// ── AST ────────────────────────────────────────────────────────────────────────

type Expr =
  | { type: "AND";     left: Expr; right: Expr }
  | { type: "OR";      left: Expr; right: Expr }
  | { type: "NOT";     expr: Expr }
  | { type: "COMPARE"; field: string; op: string; value: string }
  | { type: "PROTO";   name: string };

// ── Recursive-descent parser ───────────────────────────────────────────────────

function buildParser(toks: Tok[]) {
  let pos = 0;
  const peek  = ()  => toks[pos];
  const eat   = ()  => toks[pos++];
  const expect = (k: TokKind) => {
    const t = eat();
    if (!t || t.kind !== k) throw new Error(`Expected ${k}, got ${t?.kind ?? "EOF"} ("${t?.text ?? ""}")`);
    return t;
  };

  function parseExpr(): Expr { return parseOr(); }

  function parseOr(): Expr {
    let left = parseAnd();
    while (peek()?.kind === "OR") { eat(); left = { type: "OR", left, right: parseAnd() }; }
    return left;
  }

  function parseAnd(): Expr {
    let left = parseNot();
    while (peek()?.kind === "AND") { eat(); left = { type: "AND", left, right: parseNot() }; }
    return left;
  }

  function parseNot(): Expr {
    if (peek()?.kind === "NOT") { eat(); return { type: "NOT", expr: parsePrimary() }; }
    return parsePrimary();
  }

  function parsePrimary(): Expr {
    const t = peek();
    if (!t) throw new Error("Unexpected end of filter expression");

    // Parenthesised group
    if (t.kind === "LPAREN") {
      eat();
      const expr = parseExpr();
      expect("RPAREN");
      return expr;
    }

    // IDENT: either field comparison or bare protocol name
    if (t.kind === "IDENT") {
      eat();
      const next = peek();
      if (next?.kind === "OP") {
        const op  = eat().text;
        const val = eat();
        if (!val) throw new Error(`Missing value after "${t.text} ${op}"`);
        return { type: "COMPARE", field: t.text, op, value: val.text };
      }
      // bare name → protocol filter
      return { type: "PROTO", name: t.text };
    }

    throw new Error(`Unexpected token: ${t.kind} "${t.text}"`);
  }

  return { parseExpr, remaining: () => toks.length - pos };
}

// ── Evaluator ─────────────────────────────────────────────────────────────────

function evalCompare(pkt: Packet, field: string, op: string, value: string): boolean {
  const f = field.toLowerCase();

  // Helper: compare a string field
  const cmp = (actual: string | number | null | undefined): boolean => {
    if (actual == null) return false;
    const a = String(actual);
    const b = value;
    switch (op) {
      case "==":       return a === b;
      case "!=":       return a !== b;
      case ">":        return Number(a) > Number(b);
      case "<":        return Number(a) < Number(b);
      case ">=":       return Number(a) >= Number(b);
      case "<=":       return Number(a) <= Number(b);
      case "contains": return a.toLowerCase().includes(b.toLowerCase());
      case "matches": {
        try { return new RegExp(b, "i").test(a); } catch { return false; }
      }
      default: return false;
    }
  };

  // ip.addr — match either src or dst
  if (f === "ip.addr") {
    const srcOk = cmp(pkt.src_ip);
    const dstOk = cmp(pkt.dst_ip);
    return op === "!=" ? srcOk && dstOk : srcOk || dstOk;
  }

  // tcp.port / udp.port / port — match either src or dst port
  if (f === "tcp.port" || f === "udp.port" || f === "port") {
    const srcOk = cmp(pkt.src_port);
    const dstOk = cmp(pkt.dst_port);
    return op === "!=" ? srcOk && dstOk : srcOk || dstOk;
  }

  // Specific field mappings
  switch (f) {
    case "ip.src":
    case "ip.source":       return cmp(pkt.src_ip);
    case "ip.dst":
    case "ip.destination":  return cmp(pkt.dst_ip);
    case "tcp.srcport":
    case "udp.srcport":     return cmp(pkt.src_port);
    case "tcp.dstport":
    case "udp.dstport":     return cmp(pkt.dst_port);
    case "frame.len":
    case "frame.length":    return cmp(pkt.length);
    case "frame.number":    return cmp(pkt.id);
    case "ip.proto":
    case "frame.protocols": return cmp(pkt.protocol);
    default:                return false;
  }
}

function evalExpr(pkt: Packet, expr: Expr): boolean {
  switch (expr.type) {
    case "AND":     return evalExpr(pkt, expr.left) && evalExpr(pkt, expr.right);
    case "OR":      return evalExpr(pkt, expr.left) || evalExpr(pkt, expr.right);
    case "NOT":     return !evalExpr(pkt, expr.expr);
    case "COMPARE": return evalCompare(pkt, expr.field, expr.op, expr.value);
    case "PROTO": {
      const name  = expr.name.toLowerCase();
      const proto = (pkt.protocol ?? "").toLowerCase();
      const layers = (pkt.layers ?? []).map(l => l.toLowerCase());
      const info  = (pkt.info   ?? "").toLowerCase();
      return (
        proto === name ||
        proto.includes(name) ||
        layers.includes(name) ||
        // Special aliases
        (name === "http" && (proto.startsWith("http") || info.includes("http"))) ||
        (name === "tls"  && (proto === "ssl" || proto.includes("tls"))) ||
        (name === "ssl"  && (proto === "tls" || proto.includes("ssl")))
      );
    }
  }
}

// ── Public API ────────────────────────────────────────────────────────────────

export type FilterFn = (pkt: Packet) => boolean;

export type CompileResult =
  | { ok: true;  fn: FilterFn; error: null }
  | { ok: false; fn: null;     error: string };

/**
 * Compile a Wireshark display filter string into a predicate function.
 * Returns `{ ok: true, fn }` on success, `{ ok: false, error }` on parse error.
 * An empty filter compiles to a pass-through predicate.
 */
export function compileFilter(filter: string): CompileResult {
  if (!filter.trim()) {
    return { ok: true, fn: () => true, error: null };
  }
  try {
    const toks = tokenize(filter);
    const { parseExpr, remaining } = buildParser(toks);
    const ast = parseExpr();
    if (remaining() > 0) {
      throw new Error(`Unexpected tokens near "${toks[toks.length - remaining()].text}"`);
    }
    return { ok: true, fn: (pkt: Packet) => evalExpr(pkt, ast), error: null };
  } catch (e: unknown) {
    const msg = e instanceof Error ? e.message : "Invalid filter";
    return { ok: false, fn: null, error: msg };
  }
}
