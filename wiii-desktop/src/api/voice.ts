import { getClient } from "./client";

export interface VoiceStatusResponse {
  enabled: boolean;
  configured: boolean;
  provider: "elevenlabs";
  voice_id: string;
  model_id: string;
  output_format: string;
  reason?: string | null;
}

export interface VoiceConfigResponse extends VoiceStatusResponse {
  persisted: boolean;
  updated_at?: string | null;
  key_hint?: string | null;
}

export interface VoiceConfigUpdate {
  enabled?: boolean;
  api_key?: string;
  clear_api_key?: boolean;
  voice_id?: string;
  model_id?: string;
  output_format?: string;
}

async function streamToBlob(
  stream: ReadableStream<Uint8Array>,
  type = "audio/mpeg",
): Promise<Blob> {
  const reader = stream.getReader();
  const chunks: Uint8Array[] = [];
  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      if (value) chunks.push(value);
    }
  } finally {
    reader.releaseLock();
  }
  const parts = chunks.map((chunk) => {
    const copy = new ArrayBuffer(chunk.byteLength);
    new Uint8Array(copy).set(chunk);
    return copy;
  });
  return new Blob(parts, { type });
}

export async function getVoiceStatus(): Promise<VoiceStatusResponse> {
  return getClient().get<VoiceStatusResponse>("/api/v1/voice/status");
}

export async function getVoiceConfig(): Promise<VoiceConfigResponse> {
  return getClient().get<VoiceConfigResponse>("/api/v1/voice/config");
}

export async function updateVoiceConfig(
  update: VoiceConfigUpdate,
): Promise<VoiceConfigResponse> {
  return getClient().put<VoiceConfigResponse>("/api/v1/voice/config", update);
}

export async function synthesizePointySpeech(text: string): Promise<Blob> {
  const stream = await getClient().postStream("/api/v1/voice/pointy/tts", {
    text,
  });
  return streamToBlob(stream);
}
