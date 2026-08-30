"use client";

import { useState, useCallback, useRef, useEffect } from "react";
import { UploadArea } from "@/components/UploadArea";
import { ApiKeyInput } from "@/components/ApiKeyInput";
import { ProgressView } from "@/components/ProgressView";
import { SongPlayer } from "@/components/SongPlayer";

export type AppState = "idle" | "ready" | "processing" | "done" | "error";
export type Mode = "word" | "sentence";

export interface WordPair {
  word: string;
  meaning: string;
}

export interface LogEntry {
  step: string;
  message: string;
}

const API_URL = process.env.NEXT_PUBLIC_API_URL || "";
const API_KEY_STORAGE = "utango_gemini_api_key";

export default function Home() {
  const [state, setState] = useState<AppState>("idle");
  const [mode, setMode] = useState<Mode>("word");
  const [file, setFile] = useState<File | null>(null);
  const [previewUrl, setPreviewUrl] = useState<string>("");
  const [apiKey, setApiKey] = useState<string>("");
  const [progress, setProgress] = useState<number>(0);
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [jobId, setJobId] = useState<string>("");
  const [lyrics, setLyrics] = useState<string>("");
  const [wordPairs, setWordPairs] = useState<WordPair[]>([]);
  const [errorMessage, setErrorMessage] = useState<string>("");
  const abortRef = useRef<AbortController | null>(null);

  // 起動時に保存済みキーを復元
  useEffect(() => {
    try {
      const saved = localStorage.getItem(API_KEY_STORAGE);
      if (saved) setApiKey(saved);
    } catch {
      // localStorage が使えない環境では無視
    }
  }, []);

  const handleApiKeyChange = useCallback((key: string) => {
    setApiKey(key);
    try {
      localStorage.setItem(API_KEY_STORAGE, key);
    } catch {
      // 保存できなくても続行可能
    }
  }, []);

  const addLog = useCallback((step: string, message: string) => {
    setLogs((prev) => [...prev, { step, message }]);
  }, []);

  const handleFileSelect = useCallback((selectedFile: File) => {
    setFile(selectedFile);
    setPreviewUrl(URL.createObjectURL(selectedFile));
    setState("ready");
    setLogs([]);
    setProgress(0);
    setErrorMessage("");
    setJobId("");
    setLyrics("");
    setWordPairs([]);
  }, []);

  const handleRemoveFile = useCallback(() => {
    setFile(null);
    setPreviewUrl("");
    setState("idle");
  }, []);

  const handleGenerate = useCallback(async () => {
    if (!file) return;

    // 共有キー方式: apiKey が空でもサーバー側のフォールバックキーで処理するため、
    // ここでの必須ガードは行わない。キーがある人だけ自分のキーが優先される。

    setState("processing");
    setProgress(0);
    setLogs([]);
    setErrorMessage("");

    try {
      const formData = new FormData();
      formData.append("file", file);
      formData.append("mode", mode);
      // 入力がある場合のみユーザーのキーを送信。空ならサーバーのフォールバックに任せる。
      const trimmedKey = apiKey.trim();
      if (trimmedKey) {
        formData.append("api_key", trimmedKey);
      }

      const res = await fetch(`${API_URL}/generate`, {
        method: "POST",
        body: formData,
      });

      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || "アップロードに失敗しました");
      }

      const data = await res.json();
      const currentJobId = data.job_id;
      setJobId(currentJobId);

      const abort = new AbortController();
      abortRef.current = abort;

      const eventRes = await fetch(`${API_URL}/progress/${currentJobId}`, {
        signal: abort.signal,
      });

      if (!eventRes.ok || !eventRes.body) {
        throw new Error("進捗の取得に失敗しました");
      }

      const reader = eventRes.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() || "";

        for (const line of lines) {
          if (!line.startsWith("data: ")) continue;
          try {
            const event = JSON.parse(line.slice(6));
            if (event.step === "keepalive") continue;

            if (event.progress >= 0) setProgress(event.progress);
            if (event.message) addLog(event.step, event.message);

            if (event.step === "done") {
              setLyrics(event.lyrics || "");
              setWordPairs(event.word_pairs || []);
              setState("done");
              return;
            }
            if (event.step === "error") {
              throw new Error(event.message || "処理中にエラーが発生しました");
            }
          } catch (parseErr) {
            if (parseErr instanceof SyntaxError) continue;
            throw parseErr;
          }
        }
      }
    } catch (err: unknown) {
      if (err instanceof DOMException && err.name === "AbortError") return;
      const message = err instanceof Error ? err.message : "不明なエラー";
      setErrorMessage(message);
      setState("error");
    }
  }, [file, apiKey, mode, addLog]);

  const handleReset = useCallback(() => {
    if (abortRef.current) abortRef.current.abort();
    setFile(null);
    setPreviewUrl("");
    setState("idle");
    setProgress(0);
    setLogs([]);
    setJobId("");
    setLyrics("");
    setWordPairs([]);
    setErrorMessage("");
  }, []);

  const modeButtonStyle = (active: boolean): React.CSSProperties => ({
    flex: 1,
    padding: "12px 8px",
    borderRadius: 10,
    border: active ? "2px solid var(--primary)" : "1px solid var(--border)",
    background: active ? "var(--primary)" : "var(--card)",
    color: active ? "var(--primary-foreground)" : "var(--foreground)",
    fontSize: 15,
    fontWeight: 700,
    cursor: "pointer",
  });

  return (
    <div style={{ minHeight: "100vh", display: "flex", flexDirection: "column" }}>
      {/* ヘッダー */}
      <header
        style={{
          padding: "16px 20px",
          borderBottom: "1px solid var(--border)",
          background: "var(--card)",
          display: "flex",
          alignItems: "center",
          gap: 8,
        }}
      >
        <span style={{ fontSize: 24 }}>🎵</span>
        <span style={{ fontSize: 20, fontWeight: 700, color: "var(--primary)" }}>
          utango
        </span>
        <span style={{ fontSize: 12, color: "var(--muted-foreground)" }}>
          うたんご
        </span>
      </header>

      {/* メイン */}
      <main
        style={{
          flex: 1,
          width: "100%",
          maxWidth: 520,
          margin: "0 auto",
          padding: "24px 16px",
          display: "flex",
          flexDirection: "column",
          gap: 20,
        }}
      >
        {(state === "idle" || state === "ready") && (
          <>
            <div style={{ textAlign: "center" }}>
              <h1 style={{ fontSize: 22, fontWeight: 700, margin: "0 0 8px" }}>
                英単語が、歌になる。
              </h1>
              <p style={{ fontSize: 14, color: "var(--muted-foreground)", margin: 0 }}>
                単語帳をスマホで撮るだけ。<br />
                覚えたい単語のオリジナル暗記ソングをAIが作ります。
              </p>
            </div>

            {/* モード選択 */}
            <div>
              <div style={{ display: "flex", gap: 8 }}>
                <button
                  onClick={() => setMode("word")}
                  style={modeButtonStyle(mode === "word")}
                >
                  英単語で歌う
                </button>
                <button
                  onClick={() => setMode("sentence")}
                  style={modeButtonStyle(mode === "sentence")}
                >
                  英文で歌う
                </button>
              </div>
              {mode === "sentence" && (
                <p
                  style={{
                    fontSize: 12,
                    color: "var(--muted-foreground)",
                    margin: "8px 4px 0",
                  }}
                >
                  英文と日本語訳を交互に。意味ごと覚えられます。
                </p>
              )}
            </div>

            <UploadArea
              previewUrl={previewUrl}
              onFileSelect={handleFileSelect}
              onRemoveFile={handleRemoveFile}
            />

            {state === "ready" && (
              <button
                onClick={handleGenerate}
                style={{
                  width: "100%",
                  padding: "16px",
                  borderRadius: 12,
                  border: "none",
                  background: "var(--primary)",
                  color: "var(--primary-foreground)",
                  fontSize: 17,
                  fontWeight: 700,
                  cursor: "pointer",
                }}
              >
                🎶 暗記ソングを作る
              </button>
            )}

            {/* 詳細設定: 自分の Gemini API キーを使いたい人だけ開く */}
            <details style={{ fontSize: 13 }}>
              <summary
                style={{
                  cursor: "pointer",
                  color: "var(--muted-foreground)",
                  padding: "8px 0",
                  userSelect: "none",
                }}
              >
                詳細設定（自分の API キーを使う場合）
              </summary>
              <div style={{ marginTop: 12 }}>
                <p
                  style={{
                    fontSize: 12,
                    color: "var(--muted-foreground)",
                    margin: "0 0 8px",
                  }}
                >
                  通常は入力不要です。自分の Gemini API キーで利用したい場合のみ入力してください。
                </p>
                <ApiKeyInput apiKey={apiKey} onChange={handleApiKeyChange} />
              </div>
            </details>
          </>
        )}

        {(state === "processing" || state === "error") && (
          <ProgressView
            progress={progress}
            logs={logs}
            isProcessing={state === "processing"}
            errorMessage={errorMessage}
            onRetry={handleReset}
          />
        )}

        {state === "done" && jobId && (
          <SongPlayer
            apiUrl={API_URL}
            jobId={jobId}
            lyrics={lyrics}
            wordPairs={wordPairs}
            onReset={handleReset}
          />
        )}
      </main>

      {/* フッター */}
      <footer
        style={{
          padding: "16px",
          textAlign: "center",
          fontSize: 11,
          color: "var(--muted-foreground)",
          borderTop: "1px solid var(--border)",
        }}
      >
        utango — 英単語が歌になる暗記アプリ
        <br />
        アップロードした画像と生成データは一定時間後に自動削除されます。
      </footer>
    </div>
  );
}
