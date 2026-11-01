// Measure labels with CanvasKit's SkParagraph — the browser end of the M0-7
// metrics gate (`pixi run gate:metrics`) and of the M-1 E2 spike.
//
// Usage: node tools/metrics/measure_canvaskit.cjs <corpus.json> <out.json> [fontSizePx]
//
// Fonts come from the managed font directory ($GG_FONT_DIR, else
// $CONDA_PREFIX/fonts), so both ends shape byte-identical font files. Family
// names and the run-split rules are read from src/ggcore/metrics/data/rules.json
// — the same single source the Python side uses, so the two ends cannot drift.
//
// CanvasKit's TypefaceFontProvider does NOT fall back across families: asking
// for a family that lacks a codepoint yields .notdef boxes. So each label is
// split into runs with the same "first face in the stack whose cmap covers the
// codepoint wins" rule the Python side uses, then each run is measured with its
// explicit family. `implicit_width` records the naive single-family result as
// evidence for the gap (132/200 labels in the frozen corpus).
'use strict';

const path = require('path');
const fs = require('fs');

const repoRoot = path.resolve(__dirname, '../..');
const repoRequire = require('module').createRequire(path.join(repoRoot, 'noop.cjs'));
const CanvasKitInit = repoRequire('canvaskit-wasm');

const RULES = JSON.parse(
  fs.readFileSync(path.join(repoRoot, 'src/ggcore/metrics/data/rules.json'), 'utf8'),
);
const FAMILY = Object.fromEntries(RULES.fonts.map((f) => [f.file, f.family]));
const GLUE = new Set();
for (const [low, high] of RULES.glue_ranges) {
  for (let cp = parseInt(low, 16); cp <= parseInt(high, 16); cp++) GLUE.add(cp);
}

const [, , corpusPath, outPath, sizeArg] = process.argv;
const corpus = JSON.parse(fs.readFileSync(corpusPath, 'utf8'));
const fontSizePx = sizeArg ? Number(sizeArg) : corpus.font_size_px;
const fontDir = process.env.GG_FONT_DIR || path.join(process.env.CONDA_PREFIX || '', 'fonts');
const ckBin = path.join(repoRoot, 'node_modules/canvaskit-wasm/bin');
const pkgVersion = repoRequire('canvaskit-wasm/package.json').version;

CanvasKitInit({ locateFile: (f) => path.join(ckBin, f) }).then((CK) => {
  const provider = CK.TypefaceFontProvider.Make();
  const faces = [];
  for (const file of corpus.font_stack) {
    const buf = fs.readFileSync(path.join(fontDir, file));
    const ab = buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.byteLength);
    const family = FAMILY[file] || file;
    provider.registerFont(ab, family);
    const typeface = CK.Typeface.MakeTypefaceFromData(ab);
    faces.push({ file, family, typeface });
  }
  const collection = CK.FontCollection.Make();
  collection.setDefaultFontManager(provider);

  const primary = FAMILY[corpus.font_stack[0]] || corpus.font_stack[0];
  const measure = (text, family) => {
    const textStyle = new CK.TextStyle({ fontFamilies: [family], fontSize: fontSizePx });
    const paragraphStyle = new CK.ParagraphStyle({ textStyle, maxLines: 1 });
    const builder = CK.ParagraphBuilder.MakeFromFontCollection(paragraphStyle, collection);
    builder.pushStyle(textStyle);
    builder.addText(text);
    const para = builder.build();
    para.layout(1e6);
    const out = {
      intrinsic: para.getMaxIntrinsicWidth(),
      longest: para.getLongestLine(),
    };
    para.delete();
    return out;
  };

  const covers = (face, cp) => {
    const gids = face.typeface.getGlyphIDs(String.fromCodePoint(cp));
    return gids.length > 0 && gids[0] !== 0;
  };

  const splitRuns = (text) => {
    const runs = [];
    let current = { idx: 0, text: '' };
    for (const ch of text) {
      const cp = ch.codePointAt(0);
      let idx = null;
      if (!GLUE.has(cp)) {
        idx = faces.findIndex((f) => covers(f, cp));
        if (idx < 0) idx = null;
      }
      if (idx === null) {
        current.text += ch;
        continue;
      }
      if (current.text && idx !== current.idx) {
        runs.push(current);
        current = { idx, text: '' };
      }
      current.idx = idx;
      current.text += ch;
    }
    if (current.text) runs.push(current);
    return runs;
  };

  const labels = corpus.labels.map((label) => {
    const runs = splitRuns(label.text).map((run) => {
      const m = measure(run.text, faces[run.idx].family);
      return { face: faces[run.idx].file, text: run.text, width: m.intrinsic, longest: m.longest };
    });
    const implicit = measure(label.text, primary);
    return {
      id: label.id,
      category: label.category,
      width: runs.reduce((a, r) => a + r.width, 0),
      implicit_width: implicit.intrinsic,
      runs: runs.map((r) => ({ face: r.face, text: r.text, width: r.width })),
    };
  });

  fs.writeFileSync(
    outPath,
    JSON.stringify(
      {
        engine: 'canvaskit-wasm',
        version: pkgVersion,
        node: process.version,
        font_size_px: fontSizePx,
        labels,
      },
      null,
      1,
    ) + '\n',
  );
  console.log(`canvaskit ${pkgVersion}: measured ${labels.length} labels at ${fontSizePx}px`);
});
