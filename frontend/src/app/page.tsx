"use client";

import { useState, useCallback, useRef, useEffect } from "react";
import { UploadArea } from "@/components/UploadArea";
import { ApiKeyInput } from "@/components/ApiKeyInput";
import { SongPlayer } from "@/components/SongPlayer";

export type AppState =
  | "idle"
  | "ready"
  | "extracting"
  | "editing"
  | "generating-lyrics"
  | "singing"
  | "done"
  | "error";
export type Mode = "word" | "sentence";
export type Quality = "standard" | "high";

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
// ビルド識別子。画面に表示され、古いビルドを見ていないか判別するために使う
const APP_BUILD = "2026-08-31b";

export default function Home() {
  const [state, setState] = useState<AppState>("idle");
  const [quality, setQuality] = useState<Quality>("standard");
  const [mode, setMode] = useState<Mode>("word");
  const [file, setFile] = useState<File | null>(null);
  const [previewUrl, setPreviewUrl] = useState<string>("");
  const [apiKey, setApiKey] = useState<string>("");
  const [wordPairs, setWordPairs] = useState<WordPair[]>([]);
  const [selectedPairs, setSelectedPairs] = useState<boolean[]>([]);
  const [lyrics, setLyrics] = useState<string>("");
  const [editedLyrics, setEditedLyrics] = useState<string>("");
  const [jobId, setJobId] = useState<string>("");
  const [errorMessage, setErrorMessage] = useState<string>("");
  const [statusMessage, setStatusMessage] = useState<string>("");
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    try {
      const saved = localStorage.getItem(API_KEY_STORAGE);
      if (saved) setApiKey(saved);
    } catch {}
  }, []);

  const handleApiKeyChange = useCallback((key: string) => {
    setApiKey(key);
    try { localStorage.setItem(API_KEY_STORAGE, key); } catch {}
  }, []);

  const handleFileSelect = useCallback((selectedFile: File) => {
    setFile(selectedFile);
    setPreviewUrl(URL.createObjectURL(selectedFile));
    setState("ready");
    setErrorMessage("");
    setWordPairs([]);
    setLyrics("");
    setEditedLyrics("");
    setJobId("");
  }, []);

  const handleRemoveFile = useCallback(() => {
    setFile(null);
    setPreviewUrl("");
    setState("idle");
  }, []);

  const hasApiKey = apiKey.trim().length > 0;
  const canGenerate = state === "ready" && hasApiKey;

  // ─── Step 1: 画像から単語を抽出 ─────────────────────
  const handleExtract = useCallback(async () => {
    if (!file || !apiKey.trim()) return;
    setState("extracting");
    setStatusMessage("画像から単語を読み取っています...");
    setErrorMessage("");

    try {
      const formData = new FormData();
      formData.append("file", file);
      formData.append("mode", mode);
      formData.append("api_key", apiKey.trim());

      const res = await fetch(`${API_URL}/extract`, {
        method: "POST",
        body: formData,
      });

      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || "単語の読み取りに失敗しました");
      }

      const data = await res.json();
      const pairs: WordPair[] = data.word_pairs || [];
      if (pairs.length === 0) {
        throw new Error("単語が見つかりませんでした。別の画像を試してください。");
      }
      setWordPairs(pairs);
      setSelectedPairs(pairs.map(() => true));
      setState("editing");
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : "不明なエラー";
      setErrorMessage(message);
      setState("error");
    }
  }, [file, apiKey, mode]);

  // ─── Step 2: 歌詞を生成（何度でも呼べる） ──────────
  const handleGenerateLyrics = useCallback(async () => {
    const selected = wordPairs.filter((_, i) => selectedPairs[i]);
    if (selected.length === 0) return;

    setState("generating-lyrics");
    setStatusMessage("キャッチーな歌詞を作っています...");
    setErrorMessage("");

    try {
      const formData = new FormData();
      formData.append("api_key", apiKey.trim());
      formData.append("mode", mode);
      formData.append("word_pairs_json", JSON.stringify(selected));

      const res = await fetch(`${API_URL}/lyrics`, {
        method: "POST",
        body: formData,
      });

      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || "歌詞の生成に失敗しました");
      }

      const data = await res.json();
      setLyrics(data.lyrics || "");
      setEditedLyrics(data.lyrics || "");
      setState("editing");
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : "不明なエラー";
      setErrorMessage(message);
      setState("editing");
    }
  }, [wordPairs, selectedPairs, apiKey, mode]);

  // ─── Step 3: 歌を作る（SSE） ───────────────────────
  const handleSing = useCallback(async () => {
    if (!editedLyrics.trim()) return;

    setState("singing");
    setStatusMessage(quality === "high" ? "歌を作っています..." : "音声を作っています...");
    setErrorMessage("");

    try {
      const formData = new FormData();
      formData.append("api_key", apiKey.trim());
      formData.append("lyrics", editedLyrics.trim());
      formData.append("quality", quality);

      const res = await fetch(`${API_URL}/sing`, {
        method: "POST",
        body: formData,
      });

      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || "楽曲生成の開始に失敗しました");
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
            if (event.message) setStatusMessage(event.message);

            if (event.step === "done") {
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
      setState("editing");
    }
  }, [editedLyrics, apiKey, quality]);

  // ─── リセット ───────────────────────────────────────
  const handleReset = useCallback(() => {
    if (abortRef.current) abortRef.current.abort();
    setFile(null);
    setPreviewUrl("");
    setState("idle");
    setWordPairs([]);
    setSelectedPairs([]);
    setLyrics("");
    setEditedLyrics("");
    setJobId("");
    setErrorMessage("");
    setStatusMessage("");
  }, []);

  // 歌詞を直してもう一度（done → editing に戻る）
  const handleBackToEdit = useCallback(() => {
    setState("editing");
    setJobId("");
    setErrorMessage("");
  }, []);

  const togglePair = (index: number) => {
    setSelectedPairs((prev) => {
      const next = [...prev];
      next[index] = !next[index];
      return next;
    });
  };

  const selectedCount = selectedPairs.filter(Boolean).length;
  const hasLyrics = lyrics.trim().length > 0;

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

  const qualityButtonStyle = (active: boolean): React.CSSProperties => ({
    flex: 1,
    padding: "12px 8px",
    borderRadius: 10,
    border: active ? "2px solid var(--primary)" : "1px solid var(--border)",
    background: active ? "var(--primary)" : "var(--card)",
    color: active ? "var(--primary-foreground)" : "var(--foreground)",
    fontSize: 14,
    fontWeight: 700,
    cursor: "pointer",
  });

  const btnPrimary: React.CSSProperties = {
    width: "100%",
    padding: "14px",
    borderRadius: 12,
    border: "none",
    background: "var(--primary)",
    color: "var(--primary-foreground)",
    fontSize: 16,
    fontWeight: 700,
    cursor: "pointer",
  };

  const btnSecondary: React.CSSProperties = {
    width: "100%",
    padding: "14px",
    borderRadius: 12,
    border: "1px solid var(--border)",
    background: "var(--card)",
    color: "var(--foreground)",
    fontSize: 15,
    fontWeight: 600,
    cursor: "pointer",
  };

  return (
    <div style={{ minHeight: "100vh", display: "flex", flexDirection: "column" }}>
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
        <span style={{ fontSize: 20, fontWeight: 700, color: "var(--primary)" }}>utango</span>
        <span style={{ fontSize: 12, color: "var(--muted-foreground)" }}>うたんご</span>
      </header>

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
        {/* ─── 初期画面: APIキー・モード・画像アップ ─── */}
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

            <ApiKeyInput apiKey={apiKey} onChange={handleApiKeyChange} />
            {!hasApiKey && (
              <p style={{ fontSize: 12, color: "var(--error, #ef5777)", margin: "-12px 0 0", padding: "0 4px" }}>
                ※ 利用するには Gemini API キーの入力が必要です
              </p>
            )}

            <div>
              <div style={{ display: "flex", gap: 8 }}>
                <button onClick={() => setMode("word")} style={modeButtonStyle(mode === "word")}>
                  英単語で歌う
                </button>
                <button onClick={() => setMode("sentence")} style={modeButtonStyle(mode === "sentence")}>
                  英文で歌う
                </button>
              </div>
            </div>

            <UploadArea previewUrl={previewUrl} onFileSelect={handleFileSelect} onRemoveFile={handleRemoveFile} />

            {state === "ready" && (
              <button
                onClick={handleExtract}
                disabled={!canGenerate}
                style={{
                  ...btnPrimary,
                  background: canGenerate ? "var(--primary)" : "var(--muted)",
                  color: canGenerate ? "var(--primary-foreground)" : "var(--muted-foreground)",
                  cursor: canGenerate ? "pointer" : "not-allowed",
                  opacity: canGenerate ? 1 : 0.6,
                }}
              >
                🔍 単語を読み取る
              </button>
            )}
          </>
        )}

        {/* ─── 読み取り中 ─── */}
        {state === "extracting" && (
          <div style={{ textAlign: "center", padding: "40px 0" }}>
            <div style={{ fontSize: 40, marginBottom: 16 }}>🔍</div>
            <p style={{ fontSize: 16, fontWeight: 600 }}>{statusMessage}</p>
          </div>
        )}

        {/* ─── 歌詞生成中 ─── */}
        {state === "generating-lyrics" && (
          <div style={{ textAlign: "center", padding: "40px 0" }}>
            <div style={{ fontSize: 40, marginBottom: 16 }}>✍️</div>
            <p style={{ fontSize: 16, fontWeight: 600 }}>{statusMessage}</p>
          </div>
        )}

        {/* ─── 編集画面: 単語選択 + 歌詞編集 ─── */}
        {state === "editing" && (
          <>
            {/* 単語選択 */}
            <div
              style={{
                borderRadius: 16,
                background: "var(--card)",
                border: "1px solid var(--border)",
                overflow: "hidden",
              }}
            >
              <div style={{ padding: "14px 16px", borderBottom: "1px solid var(--border)" }}>
                <span style={{ fontSize: 15, fontWeight: 700 }}>
                  📝 読み取った単語（{selectedCount}/{wordPairs.length}）
                </span>
                <span style={{ fontSize: 12, color: "var(--muted-foreground)", marginLeft: 8 }}>
                  歌に入れる単語を選んでください
                </span>
              </div>
              {wordPairs.map((p, i) => (
                <div
                  key={i}
                  onClick={() => togglePair(i)}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 12,
                    padding: "12px 16px",
                    borderBottom: i < wordPairs.length - 1 ? "1px solid var(--border)" : "none",
                    cursor: "pointer",
                    opacity: selectedPairs[i] ? 1 : 0.4,
                    background: selectedPairs[i] ? "transparent" : "var(--muted)",
                  }}
                >
                  <span style={{ fontSize: 18 }}>{selectedPairs[i] ? "☑️" : "⬜"}</span>
                  <span style={{ flex: 1, fontSize: 15, fontWeight: 600 }}>{p.word}</span>
                  <span style={{ fontSize: 14, color: "var(--muted-foreground)" }}>{p.meaning}</span>
                </div>
              ))}
            </div>

            {/* 歌詞表示・編集エリア */}
            {hasLyrics && (
              <div
                style={{
                  borderRadius: 16,
                  background: "var(--card)",
                  border: "1px solid var(--border)",
                  padding: 16,
                }}
              >
                <div style={{ marginBottom: 10 }}>
                  <span style={{ fontSize: 15, fontWeight: 700 }}>🎼 歌詞</span>
                  <span style={{ fontSize: 12, color: "var(--muted-foreground)", marginLeft: 8 }}>
                    自由に編集できます
                  </span>
                </div>
                <textarea
                  value={editedLyrics}
                  onChange={(e) => setEditedLyrics(e.target.value)}
                  style={{
                    width: "100%",
                    minHeight: 200,
                    padding: 12,
                    borderRadius: 8,
                    border: "1px solid var(--border)",
                    background: "var(--background)",
                    color: "var(--foreground)",
                    fontSize: 14,
                    lineHeight: 1.8,
                    fontFamily: "inherit",
                    resize: "vertical",
                  }}
                />
              </div>
            )}

            {/* 音声モード選択（歌詞ができてから表示） */}
            {hasLyrics && (
              <div
                style={{
                  borderRadius: 16,
                  background: "var(--card)",
                  border: "1px solid var(--border)",
                  padding: 16,
                }}
              >
                <div style={{ marginBottom: 10 }}>
                  <span style={{ fontSize: 15, fontWeight: 700 }}>🔊 音声モード</span>
                </div>
                <div style={{ display: "flex", gap: 8 }}>
                  <button
                    onClick={() => setQuality("standard")}
                    style={qualityButtonStyle(quality === "standard")}
                  >
                    🗣️ 読み上げ
                    <br />
                    <span style={{ fontSize: 11, fontWeight: 400, opacity: 0.8 }}>無料</span>
                  </button>
                  <button
                    onClick={() => setQuality("high")}
                    style={qualityButtonStyle(quality === "high")}
                  >
                    🎵 歌（Lyria）
                    <br />
                    <span style={{ fontSize: 11, fontWeight: 400, opacity: 0.8 }}>有料キー必要</span>
                  </button>
                </div>
              </div>
            )}

            {/* エラー表示 */}
            {errorMessage && (
              <div
                style={{
                  background: "rgba(239,87,119,0.1)",
                  border: "1px solid var(--error, #ef5777)",
                  borderRadius: 12,
                  padding: 14,
                  fontSize: 14,
                  color: "var(--error, #ef5777)",
                }}
              >
                ⚠️ {errorMessage}
              </div>
            )}

            {/* アクションボタン
                歌詞生成ボタンは条件分岐の外に置き、どの状態でも必ず表示する。
                これにより「次に進むボタンが消えて操作不能になる」事故を防ぐ。 */}
            <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
              {hasLyrics && (
                <button onClick={handleSing} style={btnPrimary}>
                  {quality === "high" ? "🎶 この歌詞で歌を作る" : "🗣️ この歌詞を読み上げる"}
                </button>
              )}
              <button
                onClick={handleGenerateLyrics}
                disabled={selectedCount === 0}
                style={{
                  ...(hasLyrics ? btnSecondary : btnPrimary),
                  opacity: selectedCount === 0 ? 0.5 : 1,
                  cursor: selectedCount === 0 ? "not-allowed" : "pointer",
                }}
              >
                {hasLyrics ? "🔄 歌詞をもう一回作る" : "✍️ 歌詞を作る"}
              </button>
              <button onClick={handleReset} style={{ ...btnSecondary, fontSize: 13, color: "var(--muted-foreground)" }}>
                ← 最初からやり直す
              </button>
            </div>
          </>
        )}

        {/* ─── 楽曲生成中 ─── */}
        {state === "singing" && (
          <div style={{ textAlign: "center", padding: "40px 0" }}>
            <div style={{ fontSize: 40, marginBottom: 16 }}>🎵</div>
            <p style={{ fontSize: 16, fontWeight: 600 }}>{statusMessage}</p>
            <p style={{ fontSize: 13, color: "var(--muted-foreground)", marginTop: 8 }}>
              30秒ほどかかります...
            </p>
          </div>
        )}

        {/* ─── 完成画面 ─── */}
        {state === "done" && jobId && (
          <SongPlayer
            apiUrl={API_URL}
            jobId={jobId}
            lyrics={editedLyrics}
            wordPairs={wordPairs.filter((_, i) => selectedPairs[i])}
            onReset={handleReset}
            onEditLyrics={handleBackToEdit}
          />
        )}

        {/* ─── グローバルエラー ─── */}
        {state === "error" && (
          <div style={{ display: "flex", flexDirection: "column", gap: 12, padding: "20px 0" }}>
            <div
              style={{
                background: "rgba(239,87,119,0.1)",
                border: "1px solid var(--error, #ef5777)",
                borderRadius: 12,
                padding: 14,
                fontSize: 14,
                color: "var(--error, #ef5777)",
              }}
            >
              ⚠️ {errorMessage}
            </div>
            <button onClick={handleReset} style={btnSecondary}>
              もう一度ためす
            </button>
          </div>
        )}
      </main>

      <footer
        style={{
          padding: "16px",
          textAlign: "center",
          fontSize: 11,
          color: "var(--muted-foreground)",
          borderTop: "1px solid var(--border)",
        }}
      >
        utango — 英単語が歌になる暗記アプリ（build {APP_BUILD}）
      </footer>
    </div>
  );
}
