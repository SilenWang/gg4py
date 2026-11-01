// Measure every label in the frozen corpus with CanvasKit's SkParagraph.
// Usage: node measure_canvaskit.cjs <corpus.json> <out.json> [fontSizePx]
// Fonts come from the pixi environment ($CONDA_PREFIX/fonts), so both sides of
// the comparison shape byte-identical font files.
//
// CanvasKit's TypefaceFontProvider does NOT fall back across families: asking
// for a family that lacks a codepoint yields .notdef boxes. So this harness
// splits each label into runs with the same "first face that covers the
// codepoint wins" rule the CPython side uses (and the TS SVG serializer will
// need), then measures each run with its explicit family. `implicit*` fields
// record what the naive single-family path produces, as evidence for the gap.
'use strict';

const path = require('path');
const fs = require('fs');

const repoRoot = path.resolve(__dirname, '../../..');
const repoRequire = require('module').createRequire(path.join(repoRoot, 'noop.cjs'));
const CanvasKitInit = repoRequire('canvaskit-wasm');

const [, , corpusPath, outPath, sizeArg] = process.argv;
const corpus = JSON.parse(fs.readFileSync(corpusPath, 'utf8'));
const fontSizePx = sizeArg ? Number(sizeArg) : corpus.font_size_px;
const fontDir = path.join(process.env.CONDA_PREFIX || '', 'fonts');
const ckBin = path.join(repoRoot, 'node_modules/canvaskit-wasm/bin');
const pkgVersion = repoRequire('canvaskit-wasm/package.json').version;

// Skia family names for the files pinned in the corpus font_stack.
const FAMILY = {
  'DejaVuSans.ttf': 'DejaVu Sans',
  'NotoSansCJKsc-VF.ttf': 'Noto Sans CJK SC',
  'NotoColorEmoji.ttf': 'Noto Color Emoji',
};

// Joiners, selectors and combining marks never start a new font run.
const GLUE = new Set([0x200d, 0xfe0e, 0xfe0f, 0x200c]);

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
  console.log(`canvaskit ${pkgVersion}: measured ${labels.length} labels`);
});
