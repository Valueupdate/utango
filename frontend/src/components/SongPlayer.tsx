"use client";

import { useState } from "react";
import type { WordPair } from "@/app/page";

interface SongPlayerProps {
  apiUrl: string;
  jobId: string;
  lyrics: string;
  wordPairs: WordPair[];
  onReset: () => void;
  onEditLyrics: () => void;
}

type Tab = "words" | "lyrics";

export function SongPlayer({ apiUrl, jobId, lyrics, wordPairs, onReset, onEditLyrics }: SongPlayerProps) {
  const [tab, setTab] = useState<Tab>("lyrics");
  const audioUrl = `${apiUrl}/download/${jobId}`;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <div
        style={{
          borderRadius: 16,
          background: "var(--card)",
          border: "1px solid var(--border)",
          padding: 20,
          textAlign: "center",
        }}
      >
        <div style={{ fontSize: 40 }}>🎉</div>
        <h2 style={{ fontSize: 18, fontWeight: 700, margin: "8px 0 4px" }}>
          暗記ソングができました！
        </h2>
        <p style={{ fontSize: 13, color: "var(--muted-foreground)", margin: "0 0 16px" }}>
          歌を聴きながら覚えよう
        </p>
        <audio src={audioUrl} controls autoPlay style={{ width: "100%" }} />
      </div>

      <div
        style={{
          display: "flex",
          gap: 6,
          background: "var(--muted)",
          borderRadius: 12,
          padding: 4,
        }}
      >
        {([
          { key: "lyrics" as Tab, label: "🎼 歌詞" },
          { key: "words" as Tab, label: "📝 単語リスト" },
        ]).map((t) => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            style={{
              flex: 1,
              padding: "10px",
              borderRadius: 8,
              border: "none",
              background: tab === t.key ? "var(--card)" : "transparent",
              color: tab === t.key ? "var(--primary)" : "var(--muted-foreground)",
              fontSize: 14,
              fontWeight: tab === t.key ? 700 : 500,
              cursor: "pointer",
            }}
          >
            {t.label}
          </button>
        ))}
      </div>

      {tab === "lyrics" && (
        <div
          style={{
            borderRadius: 16,
            background: "var(--card)",
            border: "1px solid var(--border)",
            padding: 18,
            fontSize: 14,
            lineHeight: 1.9,
            whiteSpace: "pre-wrap",
            color: "var(--foreground)",
          }}
        >
          {lyrics}
        </div>
      )}

      {tab === "words" && (
        <div
          style={{
            borderRadius: 16,
            background: "var(--card)",
            border: "1px solid var(--border)",
            overflow: "hidden",
          }}
        >
          {wordPairs.map((p, i) => (
            <div
              key={i}
              style={{
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
                padding: "14px 16px",
                borderBottom: i < wordPairs.length - 1 ? "1px solid var(--border)" : "none",
              }}
            >
              <span style={{ fontSize: 16, fontWeight: 600 }}>{p.word}</span>
              <span style={{ fontSize: 15, color: "var(--muted-foreground)" }}>{p.meaning}</span>
            </div>
          ))}
        </div>
      )}

      <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        <button
          onClick={onEditLyrics}
          style={{
            width: "100%",
            padding: "14px",
            borderRadius: 12,
            border: "1px solid var(--border)",
            background: "var(--card)",
            color: "var(--foreground)",
            fontSize: 15,
            fontWeight: 600,
            cursor: "pointer",
          }}
        >
          ✏️ 歌詞を直してもう一度作る
        </button>
        <button
          onClick={onReset}
          style={{
            width: "100%",
            padding: "14px",
            borderRadius: 12,
            border: "1px solid var(--border)",
            background: "var(--card)",
            color: "var(--muted-foreground)",
            fontSize: 13,
            fontWeight: 600,
            cursor: "pointer",
          }}
        >
          ＋ 別の単語帳でもう1曲つくる
        </button>
      </div>
    </div>
  );
}
