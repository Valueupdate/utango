"use client";

import type { LogEntry } from "@/app/page";

interface ProgressViewProps {
  progress: number;
  logs: LogEntry[];
  isProcessing: boolean;
  errorMessage: string;
  onRetry: () => void;
}

const STEPS = [
  { key: "extract", icon: "🔍", label: "単語を読み取る" },
  { key: "lyrics", icon: "✍️", label: "歌詞を作る" },
  { key: "music", icon: "🎵", label: "歌を作る" },
];

export function ProgressView({ progress, logs, isProcessing, errorMessage, onRetry }: ProgressViewProps) {
  const latestStep = logs.length > 0 ? logs[logs.length - 1].step : "extract";
  const latestMessage = logs.length > 0 ? logs[logs.length - 1].message : "準備しています...";

  const stepIndex = STEPS.findIndex((s) => s.key === latestStep);

  return (
    <div
      style={{
        borderRadius: 16,
        background: "var(--card)",
        border: "1px solid var(--border)",
        padding: 20,
        display: "flex",
        flexDirection: "column",
        gap: 16,
      }}
    >
      {/* ステップインジケーター */}
      <div style={{ display: "flex", justifyContent: "space-between", gap: 8 }}>
        {STEPS.map((step, i) => {
          const isActive = i === stepIndex && isProcessing;
          const isDone = i < stepIndex || (!isProcessing && !errorMessage);
          return (
            <div
              key={step.key}
              style={{
                flex: 1,
                textAlign: "center",
                opacity: isActive || isDone ? 1 : 0.35,
              }}
            >
              <div style={{ fontSize: 28 }}>{isDone ? "✅" : step.icon}</div>
              <div style={{ fontSize: 11, marginTop: 4, fontWeight: isActive ? 700 : 400 }}>
                {step.label}
              </div>
            </div>
          );
        })}
      </div>

      {/* プログレスバー */}
      {!errorMessage && (
        <div>
          <div
            style={{
              height: 8,
              borderRadius: 4,
              background: "var(--muted)",
              overflow: "hidden",
            }}
          >
            <div
              style={{
                height: "100%",
                width: `${Math.max(0, progress)}%`,
                background: "var(--primary)",
                borderRadius: 4,
                transition: "width 0.4s ease",
              }}
            />
          </div>
          <p style={{ fontSize: 13, color: "var(--muted-foreground)", margin: "10px 0 0", textAlign: "center" }}>
            {latestMessage}
          </p>
        </div>
      )}

      {/* エラー表示 */}
      {errorMessage && (
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          <div
            style={{
              background: "rgba(239,87,119,0.1)",
              border: "1px solid var(--error)",
              borderRadius: 12,
              padding: 14,
              fontSize: 14,
              color: "var(--error)",
            }}
          >
            ⚠️ {errorMessage}
          </div>
          <button
            onClick={onRetry}
            style={{
              padding: "12px",
              borderRadius: 12,
              border: "none",
              background: "var(--primary)",
              color: "var(--primary-foreground)",
              fontSize: 15,
              fontWeight: 700,
              cursor: "pointer",
            }}
          >
            もう一度ためす
          </button>
        </div>
      )}
    </div>
  );
}
