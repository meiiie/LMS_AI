import { useState } from "react";
import { Download } from "lucide-react";
import type { ArtifactData } from "@/api/types";
import { useSettingsStore } from "@/stores/settings-store";
import { resolveArtifactFileUrl } from "@/lib/artifact-file";

interface Props {
  artifact: ArtifactData;
  mode: "card" | "panel";
}

function resolveChartSrc(
  artifact: ArtifactData,
  fileUrl: string | null,
): string | null {
  const imageUrl = artifact.metadata?.image_url;
  if (typeof imageUrl === "string" && imageUrl) {
    return imageUrl.startsWith("data:")
      ? imageUrl
      : `data:image/png;base64,${imageUrl}`;
  }
  if (artifact.content.startsWith("data:")) {
    return artifact.content;
  }
  if (
    /^[A-Za-z0-9+/=\r\n]+$/.test(artifact.content.trim()) &&
    artifact.content.trim().length > 64
  ) {
    return `data:image/png;base64,${artifact.content}`;
  }
  return fileUrl;
}

export default function ChartArtifact({ artifact, mode }: Props) {
  const serverUrl = useSettingsStore((s) => s.settings.server_url);
  const [imgError, setImgError] = useState(false);
  const fileUrl = resolveArtifactFileUrl(artifact, serverUrl);
  const src = resolveChartSrc(artifact, fileUrl);

  if (imgError || !src) {
    return (
      <div className="p-4 text-sm text-text-tertiary text-center space-y-3">
        <div>Không thể hiển thị xem trước biểu đồ ngay trong khung này.</div>
        {fileUrl && (
          <a
            href={fileUrl}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-1.5 px-3 py-2 rounded-xl bg-surface-tertiary hover:bg-border text-text-secondary hover:text-text transition-colors text-xs"
          >
            <Download size={14} />
            Mở tệp biểu đồ
          </a>
        )}
      </div>
    );
  }

  return (
    <div className={mode === "card" ? "p-2" : "p-4"}>
      <img
        src={src}
        alt={artifact.title}
        onError={() => setImgError(true)}
        className={`rounded-lg bg-white ${mode === "card" ? "max-h-[200px]" : "max-w-full"} mx-auto`}
      />
    </div>
  );
}
