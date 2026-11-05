/**
 * M3-4 · CodeMirror 6：Python 高亮 + 缩进 + 快捷键。
 *
 * 只做编辑器本身（文档状态、高亮、缩进、Ctrl/Cmd+Enter），页面逻辑在
 * `web/editor/main.js`。打成一个 ES module（`web/editor/dist/editor.js`，esbuild），
 * 页面按需 import——CodeMirror 与渲染器并行下载，不挡首屏。
 *
 * 为什么不引一个「编辑器框架」：编辑器里只有**一段 Python**，没有文件树、没有多标签、
 * 没有 LSP。CodeMirror 6 的 `basicSetup` + `@codemirror/lang-python` 就是需求全文。
 */

import { basicSetup } from "codemirror";
import { EditorState } from "@codemirror/state";
import { EditorView, keymap } from "@codemirror/view";
import { indentUnit } from "@codemirror/language";
import { python } from "@codemirror/lang-python";

export interface EditorOptions {
  doc: string;
  onChange: (text: string) => void;
  onRun: () => void;
}

export interface EditorHandle {
  view: EditorView;
  getValue: () => string;
  setValue: (text: string) => void;
  focus: () => void;
}

/** 页面里只有一个编辑器：创建一次，换示例时 `setValue`。 */
export function createEditor(parent: HTMLElement, options: EditorOptions): EditorHandle {
  const runKey = keymap.of([
    {
      key: "Mod-Enter",
      run: () => {
        options.onRun();
        return true;
      },
    },
    // Shift-Mod-Enter 也跑：Mac 上的 ⌘↩ 与 Linux/Windows 的 Ctrl+Enter 都顺手。
    {
      key: "Shift-Mod-Enter",
      run: () => {
        options.onRun();
        return true;
      },
    },
  ]);

  const state = EditorState.create({
    doc: options.doc,
    extensions: [
      runKey,
      basicSetup,
      python(),
      // 四个空格：Python 的 PEP 8 口径，也是 gg4py 仓库自己的缩进。
      indentUnit.of("    "),
      EditorView.updateListener.of((update) => {
        if (update.docChanged) options.onChange(update.state.doc.toString());
      }),
      // 编辑器主体样式跟着页面的 CSS 变量走（深浅色都只有这一套，够用）。
      EditorView.theme({
        "&": { height: "100%", fontFamily: "var(--mono)", fontSize: "13px" },
        ".cm-scroller": { overflow: "auto", lineHeight: "1.55" },
        ".cm-content": { caretColor: "var(--ink)" },
        "&.cm-focused": { outline: "none" },
        ".cm-gutters": {
          background: "var(--surface)",
          color: "var(--muted)",
          border: "none",
          borderRight: "1px solid var(--rule)",
        },
        ".cm-activeLineGutter": { background: "var(--surface-2)" },
        ".cm-activeLine": { background: "var(--surface-2)" },
      }),
    ],
  });

  const view = new EditorView({ state, parent });

  return {
    view,
    getValue: () => view.state.doc.toString(),
    setValue: (text: string) => {
      view.dispatch({
        changes: { from: 0, to: view.state.doc.length, insert: text },
      });
      view.scrollDOM.scrollTop = 0;
    },
    focus: () => view.focus(),
  };
}
