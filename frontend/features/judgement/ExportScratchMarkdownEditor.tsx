"use client";

import { markdown } from "@codemirror/lang-markdown";
import { defaultKeymap, history, historyKeymap } from "@codemirror/commands";
import { defaultHighlightStyle, syntaxHighlighting } from "@codemirror/language";
import { highlightSelectionMatches, search, searchKeymap } from "@codemirror/search";
import { EditorState } from "@codemirror/state";
import {
  EditorView,
  drawSelection,
  highlightActiveLine,
  keymap,
  lineNumbers,
} from "@codemirror/view";
import { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import rehypeKatex from "rehype-katex";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";

import { cn } from "@/lib/utils";

import "katex/dist/katex.min.css";

type Pane = "source" | "preview";

const editorTheme = EditorView.theme({
  "&": {
    height: "100%",
    fontSize: "0.875rem",
    backgroundColor: "var(--card)",
    color: "var(--foreground)",
  },
  ".cm-scroller": {
    overflow: "auto",
    fontFamily: "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace",
  },
  ".cm-content": { caretColor: "var(--navy)" },
  ".cm-gutters": {
    backgroundColor: "var(--muted)",
    color: "var(--muted-foreground)",
    borderRight: "1px solid var(--border)",
  },
  ".cm-activeLine": { backgroundColor: "color-mix(in oklch, var(--muted) 70%, transparent)" },
  ".cm-activeLineGutter": { backgroundColor: "var(--muted)" },
});

function isSplitViewport(): boolean {
  return typeof window !== "undefined" && window.matchMedia("(min-width: 1024px)").matches;
}

export function ExportScratchMarkdownEditor({
  value,
  onChange,
}: {
  value: string;
  onChange: (next: string) => void;
}) {
  const hostRef = useRef<HTMLDivElement | null>(null);
  const viewRef = useRef<EditorView | null>(null);
  const previewRef = useRef<HTMLDivElement | null>(null);
  const valueRef = useRef(value);
  const onChangeRef = useRef(onChange);
  const [pane, setPane] = useState<Pane>("source");

  valueRef.current = value;
  onChangeRef.current = onChange;

  useEffect(() => {
    const host = hostRef.current;
    if (!host) return;

    const view = new EditorView({
      parent: host,
      state: EditorState.create({
        doc: valueRef.current,
        extensions: [
          markdown(),
          syntaxHighlighting(defaultHighlightStyle, { fallback: true }),
          lineNumbers(),
          highlightActiveLine(),
          drawSelection(),
          history(),
          search(),
          highlightSelectionMatches(),
          keymap.of([...defaultKeymap, ...historyKeymap, ...searchKeymap]),
          editorTheme,
          EditorView.contentAttributes.of({ "aria-label": "Export Scratch markdown" }),
          EditorView.updateListener.of((update) => {
            if (update.docChanged) {
              onChangeRef.current(update.state.doc.toString());
            }
          }),
        ],
      }),
    });
    viewRef.current = view;

    const syncPreview = () => {
      if (!isSplitViewport()) return;
      const preview = previewRef.current;
      if (!preview) return;
      const source = view.scrollDOM;
      const maxSource = source.scrollHeight - source.clientHeight;
      const maxPreview = preview.scrollHeight - preview.clientHeight;
      if (maxSource <= 0 || maxPreview <= 0) return;
      preview.scrollTop = (source.scrollTop / maxSource) * maxPreview;
    };
    view.scrollDOM.addEventListener("scroll", syncPreview, { passive: true });

    return () => {
      view.scrollDOM.removeEventListener("scroll", syncPreview);
      view.destroy();
      viewRef.current = null;
    };
  }, []);

  useEffect(() => {
    const view = viewRef.current;
    if (!view) return;
    const current = view.state.doc.toString();
    if (current === value) return;
    view.dispatch({
      changes: { from: 0, to: current.length, insert: value },
    });
  }, [value]);

  return (
    <div className="flex h-full min-h-0 min-w-0 flex-col gap-2">
      <div
        role="tablist"
        aria-label="Export Scratch panes"
        className="flex gap-1 lg:hidden"
      >
        <button
          type="button"
          role="tab"
          aria-selected={pane === "source"}
          className={cn(
            "rounded-md px-3 py-1.5 text-sm",
            pane === "source" ? "bg-muted font-medium text-navy" : "text-muted-foreground",
          )}
          onClick={() => setPane("source")}
        >
          Source
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={pane === "preview"}
          className={cn(
            "rounded-md px-3 py-1.5 text-sm",
            pane === "preview" ? "bg-muted font-medium text-navy" : "text-muted-foreground",
          )}
          onClick={() => setPane("preview")}
        >
          Preview
        </button>
      </div>
      <div className="grid min-h-0 flex-1 gap-4 lg:grid-cols-2">
        <div
          className={cn(
            "min-h-0 min-w-0 overflow-hidden rounded-md border border-input bg-card",
            pane !== "source" && "max-lg:hidden",
          )}
        >
          <div ref={hostRef} className="h-full min-h-96" />
        </div>
        <div
          ref={previewRef}
          role="region"
          aria-label="Export Scratch preview"
          className={cn(
            "min-h-96 min-w-0 overflow-auto rounded-md border border-input bg-card p-4 text-sm text-card-foreground shadow-sm [&_a]:text-navy [&_a]:underline [&_code]:rounded [&_code]:bg-muted [&_code]:px-1 [&_h1]:font-serif [&_h2]:mt-4 [&_h2]:font-serif [&_h2]:text-base [&_h2]:font-semibold [&_ol]:mt-2 [&_ol]:list-decimal [&_ol]:pl-5 [&_p]:mt-2 [&_pre]:mt-2 [&_pre]:overflow-auto [&_pre]:rounded-md [&_pre]:bg-muted [&_pre]:p-3 [&_table]:mt-2 [&_table]:w-full [&_table]:border-collapse [&_td]:border [&_td]:border-border [&_td]:bg-card [&_td]:px-2 [&_td]:py-1 [&_th]:border [&_th]:border-border [&_th]:bg-muted [&_th]:px-2 [&_th]:py-1 [&_ul]:mt-2 [&_ul]:list-disc [&_ul]:pl-5",
            pane !== "preview" && "max-lg:hidden",
          )}
        >
          <ReactMarkdown
            remarkPlugins={[remarkGfm, remarkMath]}
            rehypePlugins={[rehypeKatex]}
            components={{
              h3: ({ children }) => (
                <h3 className="mt-8 font-serif text-base font-semibold text-navy first:mt-0">
                  {children}
                </h3>
              ),
              hr: () => <hr className="my-6 border-border" />,
            }}
          >
            {value}
          </ReactMarkdown>
        </div>
      </div>
    </div>
  );
}
