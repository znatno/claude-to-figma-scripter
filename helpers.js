// helpers.js — prepended to every user script by bin/figma-run.
//
// DO NOT paste this file inline in LLM-generated scripts; the wrapper takes
// care of prepending. The wrapper also bakes `const PROFILE = {...};` above
// this file, so COLOR / SPACE / RADIUS / TYPE / FONT_FAMILY reflect the
// design profile the user chose via AskUserQuestion (persisted to
// /tmp/claude-figma.profile.json).

const FONT_FAMILY   = PROFILE.fontFamily;
const FONT_WEIGHTS  = PROFILE.fontWeights;
const COLOR         = PROFILE.colors;
const SPACE         = PROFILE.spacing;
const RADIUS        = PROFILE.radius;
const TYPE          = PROFILE.typography;

// Token-vs-raw-literal guard. Pass a SPACE member (SPACE.m, SPACE.base, …)
// for pad/gap, or {raw: N} to opt out explicitly when 0/pixel-perfect is
// required. Rejecting raw literals is how we keep generated UIs aligned.
const _SPACE_VALUES = new Set(Object.values(SPACE).concat([0]));
function _spaceOK(name, v) {
  if (v == null) return 0;
  if (typeof v === "object" && "raw" in v) return v.raw;
  if (typeof v === "number") {
    if (_SPACE_VALUES.has(v)) return v;
    throw new Error(
      `${name}: raw literal ${v} is not a SPACE token. ` +
      `Valid: ${Object.entries(SPACE).map(([k,n]) => `${k}=${n}`).join(", ")}. ` +
      `Use SPACE.<key> or {raw: ${v}} to opt out.`
    );
  }
  return v;
}

const loadedFonts = new Set();
async function loadFont(weight) {
  const style = weight || FONT_WEIGHTS.regular;
  const key = FONT_FAMILY + "|" + style;
  if (loadedFonts.has(key)) return;
  await figma.loadFontAsync({ family: FONT_FAMILY, style });
  loadedFonts.add(key);
}

function solid(color, opacity = 1) {
  return [{ type: "SOLID", color, opacity }];
}

function frame({
  name = "Frame", parent = null, layout = "VERTICAL",
  width, height, hSize = "HUG", vSize = "HUG",
  gap = 0, pad = 0, fill = null, radius = 0,
  align = "MIN", justify = "MIN", clipsContent = false,
} = {}) {
  const g = _spaceOK("gap", gap);
  let p;
  if (typeof pad === "number" || (pad && typeof pad === "object" && "raw" in pad)) {
    const pv = _spaceOK("pad", pad);
    p = { t: pv, r: pv, b: pv, l: pv };
  } else if (pad && typeof pad === "object") {
    p = {
      t: _spaceOK("pad.t", pad.t),
      r: _spaceOK("pad.r", pad.r),
      b: _spaceOK("pad.b", pad.b),
      l: _spaceOK("pad.l", pad.l),
    };
  } else {
    p = { t: 0, r: 0, b: 0, l: 0 };
  }

  const f = figma.createFrame();
  f.name = name;
  f.layoutMode = layout;
  f.itemSpacing = g;
  f.paddingTop = p.t; f.paddingRight = p.r;
  f.paddingBottom = p.b; f.paddingLeft = p.l;
  f.primaryAxisAlignItems = justify;
  f.counterAxisAlignItems = align;
  f.cornerRadius = radius;
  f.clipsContent = clipsContent;
  f.fills = fill ? solid(fill) : [];
  if (width !== undefined)  f.resize(width,  f.height);
  if (height !== undefined) f.resize(f.width, height);
  if (parent) parent.appendChild(f);
  if (layout !== "NONE" && parent && parent.layoutMode && parent.layoutMode !== "NONE") {
    if (hSize) f.layoutSizingHorizontal = hSize;
    if (vSize) f.layoutSizingVertical   = vSize;
  }
  return f;
}

function row(opts = {}) {
  return frame(Object.assign({
    layout: "HORIZONTAL",
    gap:     opts.gap     ?? SPACE.base,
    align:   opts.align   ?? "CENTER",
    justify: opts.justify ?? "MIN",
  }, opts));
}

function col(opts = {}) {
  return frame(Object.assign({
    layout: "VERTICAL",
    gap:     opts.gap     ?? SPACE.s,
    align:   opts.align   ?? "MIN",
    justify: opts.justify ?? "MIN",
  }, opts));
}

async function text({
  value = "", parent = null, style, color,
  opacity = 1, align = "LEFT", hSize = "HUG", vSize = "HUG", width,
} = {}) {
  const s = style || TYPE.body;
  const c = color || COLOR.label;
  await loadFont(s.weight);
  const t = figma.createText();
  t.fontName = { family: FONT_FAMILY, style: s.weight };
  t.fontSize = s.size;
  if (s.lineHeight) t.lineHeight = { value: s.lineHeight, unit: "PIXELS" };
  t.characters = value;
  t.textAlignHorizontal = align;
  t.fills = solid(c, opacity);
  if (parent) parent.appendChild(t);
  if (parent && parent.layoutMode && parent.layoutMode !== "NONE") {
    if (hSize) t.layoutSizingHorizontal = hSize;
    if (vSize) t.layoutSizingVertical   = vSize;
    if (hSize === "FIXED" && width) t.resize(width, t.height);
  } else if (width) {
    t.resize(width, t.height);
  }
  return t;
}

// Icon set sourced from Lucide. Add new entries here when needed — never
// fall back to emoji or Unicode glyphs. icon() throws on misses so the
// script fails loudly rather than rendering a placeholder.
const ICONS = {
  phone:        `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor"><path d="M20.487 17.14l-4.065-3.696a1.001 1.001 0 0 0-1.391.043l-2.393 2.461c-.576-.11-1.734-.471-2.926-1.66-1.192-1.193-1.553-2.354-1.66-2.926l2.459-2.394a1 1 0 0 0 .043-1.391L6.859 3.513a1 1 0 0 0-1.391-.087l-2.17 1.861a1 1 0 0 0-.29.649c-.015.25-.301 6.172 4.291 10.766C11.305 20.707 16.324 21 17.705 21c.202 0 .326-.006.359-.008a.992.992 0 0 0 .648-.291l1.86-2.171a.997.997 0 0 0-.085-1.39z"/></svg>`,
  phoneDown:    `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor"><path d="M12 9c-1.6 0-3.15.25-4.6.72v3.1c0 .39-.23.74-.56.9-.98.49-1.87 1.12-2.66 1.85-.18.18-.43.29-.7.29-.28 0-.53-.11-.71-.29L.29 13.08c-.18-.17-.29-.42-.29-.7 0-.28.11-.53.29-.71C3.34 8.78 7.46 7 12 7s8.66 1.78 11.71 4.67c.18.18.29.43.29.71 0 .28-.11.53-.29.71l-2.48 2.48c-.18.18-.43.29-.71.29-.27 0-.52-.11-.7-.29-.79-.74-1.69-1.36-2.67-1.85-.33-.16-.56-.5-.56-.9v-3.1C15.15 9.25 13.6 9 12 9z"/></svg>`,
  mic:          `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="2" width="6" height="12" rx="3"/><path d="M19 10v2a7 7 0 0 1-14 0v-2M12 19v3"/></svg>`,
  micOff:       `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="1" y1="1" x2="23" y2="23"/><path d="M9 9v3a3 3 0 0 0 5.12 2.12M15 9.34V4a3 3 0 0 0-5.94-.6"/><path d="M17 16.95A7 7 0 0 1 5 12v-2m14 0v2a7 7 0 0 1-.11 1.23"/><line x1="12" y1="19" x2="12" y2="22"/></svg>`,
  speaker:      `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/><path d="M15.54 8.46a5 5 0 0 1 0 7.07M19.07 4.93a10 10 0 0 1 0 14.14"/></svg>`,
  keypad:       `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor"><circle cx="5" cy="5" r="1.5"/><circle cx="12" cy="5" r="1.5"/><circle cx="19" cy="5" r="1.5"/><circle cx="5" cy="12" r="1.5"/><circle cx="12" cy="12" r="1.5"/><circle cx="19" cy="12" r="1.5"/><circle cx="5" cy="19" r="1.5"/><circle cx="12" cy="19" r="1.5"/><circle cx="19" cy="19" r="1.5"/></svg>`,
  contacts:     `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75"/></svg>`,
  plus:         `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>`,
  x:            `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>`,
  check:        `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>`,
  chevronLeft:  `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="15 18 9 12 15 6"/></svg>`,
  chevronRight: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="9 18 15 12 9 6"/></svg>`,
  chevronDown:  `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 9 12 15 18 9"/></svg>`,
  search:       `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>`,
  settings:     `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09a1.65 1.65 0 0 0-1-1.51 1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09a1.65 1.65 0 0 0 1.51-1 1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33h.09a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82v.09a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>`,
  star:         `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/></svg>`,
  clock:        `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>`,
  voicemail:    `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="6" cy="12" r="4"/><circle cx="18" cy="12" r="4"/><line x1="6" y1="16" x2="18" y2="16"/></svg>`,
};

function icon(name, { size = 24, color, parent = null } = {}) {
  const svg = ICONS[name];
  if (!svg) {
    const known = Object.keys(ICONS);
    throw new Error(
      `icon(): unknown name "${name}". ` +
      `Add its SVG to ICONS in helpers.js (source: https://lucide.dev). ` +
      `Known: ${known.slice(0, 10).join(", ")}${known.length > 10 ? ", …" : ""}.`
    );
  }
  const c = color || COLOR.label;
  const rgb = `rgb(${Math.round(c.r*255)},${Math.round(c.g*255)},${Math.round(c.b*255)})`;
  const node = figma.createNodeFromSvg(svg.replace(/currentColor/g, rgb));
  node.name = `icon/${name}`;
  node.resize(size, size);
  if (parent) parent.appendChild(node);
  return node;
}

// Defense-in-depth: clean up any stray 100x100 unnamed rectangles on the
// current page before the build script runs. These can appear when Figma
// keystrokes leak to the canvas (e.g. "r" from "Scripter" activating the
// rectangle tool + a subsequent canvas click). The harness has guards in
// run.py; this is a belt-and-braces cleanup.
(function _cleanupStrayRectangles() {
  try {
    const strays = figma.currentPage.children.filter(c =>
      c.type === "RECTANGLE" &&
      /^Rectangle \d+$/.test(c.name) &&
      Math.abs(c.width  - 100) < 0.5 &&
      Math.abs(c.height - 100) < 0.5
    );
    strays.forEach(c => c.remove());
  } catch (e) { /* best effort */ }
})();
