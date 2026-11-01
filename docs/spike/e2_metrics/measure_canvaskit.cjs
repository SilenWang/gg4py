// E2 的 CanvasKit 度量：现在是门禁共享实现（tools/metrics/measure_canvaskit.cjs）
// 的薄壳。命令与输出格式不变（`pixi run spike:e2` 仍复现 M-1 的结论），但字体
// 名与 run 切分规则只有一份——读 src/ggcore/metrics/data/rules.json，不会和
// Python 端漂移。
'use strict';

require('../../../tools/metrics/measure_canvaskit.cjs');
