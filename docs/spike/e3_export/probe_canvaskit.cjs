// E3: what can the browser renderer (CanvasKit) actually write?
// Usage: node probe_canvaskit.cjs <out.json>
// Answers by enumerating the real API surface and by trying to produce a PNG,
// an SVG and a PDF from the same drawing.
'use strict';

const path = require('path');
const fs = require('fs');

const repoRoot = path.resolve(__dirname, '../../..');
const repoRequire = require('module').createRequire(path.join(repoRoot, 'noop.cjs'));
const CanvasKitInit = repoRequire('canvaskit-wasm');
const pkg = repoRequire('canvaskit-wasm/package.json');
const ckBin = path.join(repoRoot, 'node_modules/canvaskit-wasm/bin');
const outPath = process.argv[2];

CanvasKitInit({ locateFile: (f) => path.join(ckBin, f) }).then((CK) => {
  const keys = Object.keys(CK);
  const vectorish = keys.filter((k) => /pdf|svg|vector|document/i.test(k));
  const surfaceFactories = keys.filter((k) => /Surface|Canvas/.test(k)).sort();

  // A raster surface is the only browser-side output CanvasKit offers.
  const surface = CK.MakeSurface(64, 32);
  const canvas = surface.getCanvas();
  const paint = new CK.Paint();
  paint.setColor(CK.Color(0, 0, 0, 1));
  canvas.drawRect(CK.XYWHRect(0, 0, 32, 16), paint);
  const png = surface.makeImageSnapshot().encodeToBytes();
  const pngOk = png && png.length > 8 && [137, 80, 78, 71].every((b, i) => png[i] === b);
  surface.delete();
  paint.delete();

  const result = {
    engine: 'canvaskit-wasm',
    version: pkg.version,
    node: process.version,
    export_count: keys.length,
    vector_or_document_exports: vectorish,
    surface_factories: surfaceFactories,
    makes_pdf: typeof CK.MakePDFDocument !== 'undefined',
    has_svg_canvas: typeof CK.SVGCanvas !== 'undefined' || typeof CK.MakeSVGCanvas !== 'undefined',
    makes_png: !!pngOk,
    png_bytes: png ? png.length : 0,
  };
  fs.writeFileSync(outPath, JSON.stringify(result, null, 1) + '\n');
  console.log(
    `canvaskit ${pkg.version}: png=${result.makes_png} pdf=${result.makes_pdf} ` +
      `svg=${result.has_svg_canvas} vectorExports=${JSON.stringify(vectorish)}`,
  );
});
