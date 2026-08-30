"use client";

import { useRef, useCallback } from "react";

interface UploadAreaProps {
  previewUrl: string;
  onFileSelect: (file: File) => void;
  onRemoveFile: () => void;
}

export function UploadArea({ previewUrl, onFileSelect, onRemoveFile }: UploadAreaProps) {
  const cameraInputRef = useRef<HTMLInputElement>(null);
  const galleryInputRef = useRef<HTMLInputElement>(null);

  const handleChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const f = e.target.files?.[0];
      if (f) onFileSelect(f);
      e.target.value = "";
    },
    [onFileSelect]
  );

  // プレビュー表示中
  if (previewUrl) {
    return (
      <div
        style={{
          borderRadius: 16,
          overflow: "hidden",
          background: "var(--card)",
          border: "1px solid var(--border)",
          position: "relative",
        }}
      >
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src={previewUrl}
          alt="撮影した単語帳"
          style={{ width: "100%", display: "block", maxHeight: 360, objectFit: "contain", background: "#000" }}
        />
        <button
          onClick={onRemoveFile}
          style={{
            position: "absolute",
            top: 10,
            right: 10,
            width: 36,
            height: 36,
            borderRadius: "50%",
            border: "none",
            background: "rgba(0,0,0,0.6)",
            color: "#fff",
            fontSize: 18,
            cursor: "pointer",
            lineHeight: 1,
          }}
          aria-label="画像を削除"
        >
          ✕
        </button>
      </div>
    );
  }

  // 初期状態（撮影/選択ボタン）
  return (
    <>
      <input
        ref={cameraInputRef}
        type="file"
        accept="image/*"
        capture="environment"
        style={{ display: "none" }}
        onChange={handleChange}
      />
      <input
        ref={galleryInputRef}
        type="file"
        accept="image/*"
        style={{ display: "none" }}
        onChange={handleChange}
      />

      <div
        style={{
          borderRadius: 16,
          border: "2px dashed var(--border)",
          background: "var(--muted)",
          padding: "32px 20px",
          textAlign: "center",
          display: "flex",
          flexDirection: "column",
          gap: 16,
          alignItems: "center",
        }}
      >
        <div style={{ fontSize: 48 }}>📖</div>
        <p style={{ fontSize: 14, color: "var(--muted-foreground)", margin: 0 }}>
          英単語帳のページを撮影、<br />または画像を選んでください
        </p>

        <div style={{ display: "flex", flexDirection: "column", gap: 10, width: "100%", maxWidth: 280 }}>
          <button
            onClick={() => cameraInputRef.current?.click()}
            style={{
              padding: "14px",
              borderRadius: 12,
              border: "none",
              background: "var(--primary)",
              color: "var(--primary-foreground)",
              fontSize: 16,
              fontWeight: 700,
              cursor: "pointer",
            }}
          >
            📷 カメラで撮影
          </button>
          <button
            onClick={() => galleryInputRef.current?.click()}
            style={{
              padding: "14px",
              borderRadius: 12,
              border: "1px solid var(--border)",
              background: "var(--card)",
              color: "var(--foreground)",
              fontSize: 16,
              fontWeight: 600,
              cursor: "pointer",
            }}
          >
            🖼️ 画像を選ぶ
          </button>
        </div>

        <p style={{ fontSize: 11, color: "var(--muted-foreground)", margin: 0 }}>
          ※ 英単語と和訳がはっきり写った画像がおすすめです
        </p>
      </div>
    </>
  );
}
