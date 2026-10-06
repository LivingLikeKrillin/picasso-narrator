#!/usr/bin/env node
// Derive the dark-theme variant of a house-dialect SVG from the light one.
//
// GitHub cannot restyle an inlined SVG from a stylesheet the way a site can, so a README figure
// needs two files behind a <picture>. Two hand-maintained files drift, so only the light SVG is
// authored: this maps its palette onto GitHub's dark tokens and writes <name>.dark.svg.
//
//   node docs/diagrams/make-dark.mjs docs/diagrams/position.svg
//
// Re-run it after editing a light SVG, or the dark variant silently goes stale.
import { readFileSync, writeFileSync } from 'node:fs';

// light token -> dark token. Keys are the eight engineering-diagram tokens (2026-10-05 redraw):
// paper, ink, grey, hairline, governed, governed-tint, governed-text2, command. Governed is lifted
// to a light blue on dark — #2b3f6b on a dark page is unreadable — so the inverted core box
// becomes light blue with dark text (paper -> #1a1a1a) and its second line dark blue.
const MAP = {
  '#ffffff': '#1a1a1a',   // paper (box fill, text on the inverted core)
  '#262626': '#e6e6e6',   // ink
  '#6f6f6f': '#9a9a9a',   // grey
  '#bdbdbd': '#4a4a4a',   // hairline
  '#2b3f6b': '#8fa3cc',   // governed
  '#e8ebf3': '#232a3a',   // governed-tint
  '#cfd6e6': '#2b3f6b',   // governed-text2 (second line on the inverted core)
  '#b23a1d': '#d4654a',   // command
};

const src = process.argv[2];
if (!src) { console.error('usage: node make-dark.mjs <light.svg>'); process.exit(2); }

let svg = readFileSync(src, 'utf8');
const seen = new Set();
svg = svg.replace(/#[0-9a-fA-F]{6}/g, (hex) => {
  const k = hex.toLowerCase();
  if (!(k in MAP)) { seen.add(k); return hex; }
  return MAP[k];
});

if (seen.size) {
  console.error(`unmapped colours (add them to MAP): ${[...seen].join(', ')}`);
  process.exit(1);
}

const out = src.replace(/\.svg$/, '.dark.svg');
writeFileSync(out, svg);
console.log(`${out}  (${svg.length} bytes)`);
