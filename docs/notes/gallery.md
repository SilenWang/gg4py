# 画廊：三种看法（SIL-893）

案例库有 532 条 case（`docs/cases/<case>/`），每条都有 R 产线画的 `expected.svg`。
「看看它们长什么样」有三种成本完全不同的做法——按你手里有什么工具挑一条就行。

## 0. 三种看法

| 想干什么 | 命令 | 需要什么 | 看到什么 |
| --- | --- | --- | --- |
| 只看参考图 | 直接打开 `docs/cases/<case>/expected.svg` | 浏览器 / 任意 SVG 查看器，**零构建** | R（ggplot2 4.0.3 + svglite）画的那一张 |
| 看整本画廊 + 在浏览器里交互（hover / 图例开关） | `pixi run viewer:gallery && pixi run viewer:serve` | pixi（npm + tsc 由 `viewer:build` 管），**不需要 Chromium** | 532 张卡片的 `gallery.html`，点卡片进 viewer 真渲染 |
| 跑像素验证 | `pixi run viewer:cases` | 额外要 Chromium：`pixi run viewer:browsers` | 逐条 `expected.svg` × viewer DOM SVG 的 resvg 像素差（pass / fail / error / skip） |

三者的差别不是「同一件事的三种速度」，而是**验证**与**浏览**的分工：像素对拍必须
有浏览器把 IR 渲染成 DOM SVG，再取回来和参考图过同一个光栅器（`docs/notes/diff.md`
§2）；浏览只需要一张图和一份 IR。

## 1. `pixi run viewer:gallery`：静态画廊

```bash
pixi run viewer:gallery               # 全部合法 case → web/viewer/dist/gallery.html
pixi run viewer:gallery --case geom-col-basic
pixi run viewer:gallery -- --check-assets   # 额外核对资产没有空文件
```

只 `depends-on = ["viewer:build"]`（npm + tsc 出 `dist/main.js` 与 `fonts.css`），
**整条链路没有 Playwright**。每条 case 的产物（都不入库）：

| 文件 | 内容 |
| --- | --- |
| `web/viewer/gallery/<case>.ggir.cbor` | `plot.py → ggcore.plotspec → IR`；点开卡片后 viewer `fetch()` 的就是它 |
| `web/viewer/gallery/<case>.svg` | 缩略图：`docs/cases/<case>/expected.svg` 逐字节复制 |
| `web/viewer/dist/gallery.html` | 卡片链 `../index.html?scene=gallery/<case>.ggir.cbor` |

卡片状态标 **`static`**（🖼，灰边），不是 `pass`。缩略图是 R 的参考图，**没做过
像素验证**——借绿边会让人误以为「这条验证过了」，那正是 `viewer:cases` 不允许降级
成的那种假象。要红绿结论只有一条路：`viewer:cases`。

缩略图为什么不光栅化：`expected.svg` 就是「这张图该长什么样」的权威答案，浏览器
渲染 SVG 是本职；用 resvg 逐条光栅化 500+ 张会把生成时间从十几秒推到分钟级，而缩略图
不承担验证职责。

### 实测（本机，2026-11-08，532 条合法 case）

```
viewer:gallery: 532 张卡片 / 532 个 case（合法 case 总数 532）；缩略图 532 张，IR 532 份
viewer:gallery: gallery.html → web/viewer/dist/gallery.html（11.4 s）
```

`time pixi run viewer:gallery` 含 `viewer:build` 与 pixi 启动共 13.3 s；资产
`web/viewer/gallery/` 12 MB，`gallery.html` 204 KB。远低于 60 s，所以它挂在
`pixi run check` 里（放在 `viewer:cases:ci` 之后，让 check 结束时 `dist/gallery.html`
是全量 532 张卡片，而不是 CI 抽样的 28 张）。

链接全量核对（`pixi run gallery:check`，逐条 GET 卡片 href / scene / 缩略图）：

```
gallery:check: 链接 1596/1596 返回 200
gallery:check: 卡片 532 个（合法 case 532 个）
gallery:check: 全部链接 200，卡片与 case 台账一致
```

## 2. `pixi run viewer:serve`：一条命令打开

```bash
pixi run viewer:serve                 # http://127.0.0.1:8000/dist/gallery.html
pixi run viewer:serve --port 8010
```

`gallery.html` 与 `index.html` 都要 `fetch()` 卡片对应的 `.ggir.cbor`，`file://`
下浏览器会拦，所以必须有一个静态服务。服务根是 `web/viewer/`（不是仓库根）：
`gallery.html` 里的链接全按这个根解析，与 `viewer:cases` / `gallery:check` 同一口径。
端口被占用时报错会直接给出换端口的命令。

## 3. `pixi run viewer:cases`：验证，缺 Chromium 就报错

`viewer:cases` 保持原职责不变。缺浏览器时它**不会**退化成「只生成 gallery 然后
看起来全部通过」——直接退出 2，并把静态浏览的入口写在报错里。原文（本机实测，
`.playwright-browsers/` 不存在、`~/.cache/ms-playwright` 里也没有对应 revision）：

```
$ pixi run viewer:cases -- --case coord-equal
viewer:cases: 没有可用 Chromium。这是**验证**任务——每条 case 都要在 Chromium 里渲染、取回 DOM SVG，再与 expected.svg 做像素对拍；缺浏览器时它不会降级成「只生成 gallery」。
  要跑验证：`pixi run viewer:browsers`（把 Chromium 装进 .playwright-browsers/）后重跑
  只想静态看图：`pixi run viewer:gallery` 然后 `pixi run viewer:serve`
原始报错：BrowserType.launch: Executable doesn't exist at /…/gg4py/.playwright-browsers/chromium_headless_shell-1248/chrome-headless-shell-linux64/chrome-headless-shell
╔════════════════════════════════════════════════════════════╗
║ Looks like Playwright was just installed or updated.       ║
║ Please run the following command to download new browsers: ║
║                                                            ║
║     playwright install                                     ║
║                                                            ║
║ <3 Playwright Team                                         ║
╚════════════════════════════════════════════════════════════╝
```

## 4. 两条产线共用的卡片契约

HTML 只有一份实现：`tools/viewer/gallery_html.py`。`tools/viewer/cases.py`（验证产线）
与 `tools/viewer/gallery_build.py`（静态产线）都调它的 `write_gallery()`，卡片契约
（`<h2>` = case 名、`../index.html?scene=gallery/<case>.ggir.cbor`、`../gallery/<case><后缀>`）
不会两边漂。`tools/viewer/gallery_check.py` 认两种缩略图后缀（`.png` / `.svg`），
所以你生成的是哪一份它都能查。

产物继续不入库：`web/viewer/dist/` 与 `web/viewer/gallery/` 都在 `.gitignore` 里
（`pixi run viewer:build` / `viewer:cases` / `viewer:gallery` 重新生成）。
