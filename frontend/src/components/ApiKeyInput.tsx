"use client";

import { useState } from "react";

interface ApiKeyInputProps {
  apiKey: string;
  onChange: (key: string) => void;
}

export function ApiKeyInput({ apiKey, onChange }: ApiKeyInputProps) {
  const [visible, setVisible] = useState(false);

  return (
    <div
      style={{
        background: "var(--card)",
        border: "1px solid var(--border)",
        borderRadius: 12,
        padding: "14px 16px",
        display: "flex",
        flexDirection: "column",
        gap: 8,
      }}
    >
      <label style={{ fontSize: 13, fontWeight: 700, color: "var(--foreground)" }}>
        🔑 Gemini API キー
      </label>
      <div style={{ display: "flex", gap: 8 }}>
        <input
          type={visible ? "text" : "password"}
          value={apiKey}
          onChange={(e) => onChange(e.target.value)}
          placeholder="AIza... から始まるキーを貼り付け"
          autoComplete="off"
          spellCheck={false}
          style={{
            flex: 1,
            padding: "10px 12px",
            borderRadius: 8,
            border: "1px solid var(--border)",
            background: "var(--background)",
            color: "var(--foreground)",
            fontSize: 13,
            fontFamily: "monospace",
          }}
        />
        <button
          type="button"
          onClick={() => setVisible((v) => !v)}
          style={{
            padding: "0 12px",
            borderRadius: 8,
            border: "1px solid var(--border)",
            background: "var(--muted)",
            color: "var(--foreground)",
            fontSize: 13,
            cursor: "pointer",
            whiteSpace: "nowrap",
          }}
        >
          {visible ? "隠す" : "表示"}
        </button>
      </div>
      <p style={{ fontSize: 11, color: "var(--muted-foreground)", margin: 0, lineHeight: 1.5 }}>
        ※ 動作確認用（BYOK方式）。キーはサーバーに保存されず、あなたのブラウザにのみ保持され、
        生成のたびに Google への中継にのみ使われます。
        <br />
        キーは{" "}
        <a
          href="https://aistudio.google.com/app/apikey"
          target="_blank"
          rel="noopener noreferrer"
          style={{ color: "var(--primary)" }}
        >
          Google AI Studio
        </a>{" "}
        で取得できます。
      </p>
    </div>
  );
}
