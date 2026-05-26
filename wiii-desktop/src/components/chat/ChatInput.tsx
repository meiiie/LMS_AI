/**
 * Chat input — Claude Desktop style.
 * Sprint 82b: `centered` prop for elevated card styling in welcome mode.
 * Paperclip attachment button, domain selector inside card, subtle shadow.
 */
import { useState, useRef, useCallback, useEffect, useMemo } from "react";
import { AlertCircle, ArrowUp, FileText, Film, Loader2, Paperclip, Square, X } from "lucide-react";
import { parseDocumentContext } from "@/api/document-context";
import { useChatStore } from "@/stores/chat-store";
import { useToastStore } from "@/stores/toast-store";
import { useUIStore } from "@/stores/ui-store";
import { MAX_MESSAGE_LENGTH } from "@/lib/constants";
import {
  buildChatDocumentContext,
  formatBytes,
  toImageInputsFromExtractedFrames,
  toDisplayDocumentAttachment,
  type ParsedDocumentForContext,
} from "@/lib/document-context";
import type {
  DocumentContextEmbeddedAsset,
  DocumentContextExtractedImage,
  DocumentContextProvenanceLevel,
  DocumentContextSectionSnippet,
} from "@/api/document-context";
import {
  parseSkillMentions,
  detectMentionTyping,
  suggestMentions,
  type MentionSuggestion,
} from "@/lib/skill-mentions";
import { getWelcomePlaceholder } from "@/lib/greeting";
import { DomainSelector } from "./DomainSelector";
import { ModelSelector } from "./ModelSelector";
import { PointyModeToggle } from "./PointyModeToggle";
import { CapabilityStatusBar } from "./CapabilityStatusBar";
import { MentionPicker } from "./MentionPicker";
import { MentionMirror } from "./MentionMirror";
import type { ChatDocumentAttachment, ChatDocumentContext, ImageInput } from "@/api/types";

const MAX_IMAGE_ATTACHMENTS = 5;
const MAX_IMAGE_SIZE_BYTES = 10 * 1024 * 1024;
const MAX_DOCUMENT_ATTACHMENTS = 3;
const MAX_DOCUMENT_SIZE_BYTES = 20 * 1024 * 1024;
const MAX_VIDEO_SIZE_BYTES = 80 * 1024 * 1024;
const SUPPORTED_DOCUMENT_EXTENSIONS = [
  ".pdf",
  ".docx",
  ".pptx",
  ".xlsx",
  ".xls",
  ".csv",
  ".txt",
  ".md",
];
const SUPPORTED_VIDEO_EXTENSIONS = [
  ".mp4",
  ".m4v",
  ".mov",
  ".webm",
  ".mkv",
];
const ATTACH_ACCEPT = [
  "image/jpeg",
  "image/png",
  "image/webp",
  "image/gif",
  "application/pdf",
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  "application/vnd.openxmlformats-officedocument.presentationml.presentation",
  "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  "application/vnd.ms-excel",
  "text/csv",
  "text/plain",
  "text/markdown",
  "video/mp4",
  "video/quicktime",
  "video/webm",
  "video/x-matroska",
  ...SUPPORTED_DOCUMENT_EXTENSIONS,
  ...SUPPORTED_VIDEO_EXTENSIONS,
].join(",");

/** Sprint 179: Attached image before upload */
interface AttachedImage {
  data: string;
  media_type: string;
  preview: string;
}

interface AttachedDocument {
  id: string;
  file_name: string;
  mime_type?: string | null;
  media_kind?: "document" | "video";
  size_bytes: number;
  parser?: string;
  parser_chain?: string[];
  parser_warning?: string | null;
  provenance_level?: DocumentContextProvenanceLevel;
  char_count?: number;
  truncated?: boolean;
  extracted_images?: DocumentContextExtractedImage[];
  extracted_image_count?: number;
  embedded_assets?: DocumentContextEmbeddedAsset[];
  embedded_asset_count?: number;
  figure_count?: number;
  table_count?: number;
  section_snippets?: DocumentContextSectionSnippet[];
  markdown?: string;
  status: "parsing" | "ready" | "error";
  error?: string;
}

interface ChatInputProps {
  /**
   * Send message handler. Wiii Pointy v2.8 extends signature với
   * `forceSkills` — list of skill ids parsed từ `@plugin-name`
   * mentions. Backend bypasses keyword intent gates khi set, force-binds
   * tools + injects SKILL bất kể keyword match.
   */
  onSend: (
    message: string,
    images?: ImageInput[],
    forceSkills?: string[],
    documents?: ChatDocumentAttachment[],
    documentContext?: ChatDocumentContext,
  ) => void;
  onCancel: () => void;
  editingMessage?: string | null;
  onClearEdit?: () => void;
  /** Elevated card style for welcome centered composition */
  centered?: boolean;
}

function createAttachmentId(file: File): string {
  const random = globalThis.crypto?.randomUUID?.();
  return random || `${file.name}-${file.size}-${file.lastModified}-${Math.random().toString(36).slice(2)}`;
}

function getFileExtension(name: string): string {
  const idx = name.lastIndexOf(".");
  return idx >= 0 ? name.slice(idx).toLowerCase() : "";
}

function isSupportedDocumentFile(file: File): boolean {
  const ext = getFileExtension(file.name);
  return SUPPORTED_DOCUMENT_EXTENSIONS.includes(ext) || SUPPORTED_VIDEO_EXTENSIONS.includes(ext);
}

function getContextMediaKind(file: File): "document" | "video" {
  const ext = getFileExtension(file.name);
  return file.type.startsWith("video/") || SUPPORTED_VIDEO_EXTENSIONS.includes(ext)
    ? "video"
    : "document";
}

function getReadableError(err: unknown): string {
  return err instanceof Error && err.message.trim()
    ? err.message.trim()
    : "Wiii chưa đọc được tài liệu này.";
}

function toParsedDocumentForContext(doc: AttachedDocument): ParsedDocumentForContext | null {
  if (doc.status !== "ready" || !doc.markdown?.trim()) return null;
  return {
    id: doc.id,
    file_name: doc.file_name,
    mime_type: doc.mime_type,
    media_kind: doc.media_kind,
    size_bytes: doc.size_bytes,
    parser: doc.parser || "markitdown",
    parser_chain: doc.parser_chain,
    parser_warning: doc.parser_warning,
    provenance_level: doc.provenance_level,
    char_count: doc.char_count,
    extracted_images: doc.extracted_images,
    extracted_image_count: doc.extracted_image_count,
    embedded_assets: doc.embedded_assets,
    embedded_asset_count: doc.embedded_asset_count,
    figure_count: doc.figure_count,
    table_count: doc.table_count,
    section_snippets: doc.section_snippets,
    truncated: doc.truncated,
    markdown: doc.markdown,
  };
}

function DocumentAttachmentStrip({
  documents,
  onRemove,
}: {
  documents: AttachedDocument[];
  onRemove: (id: string) => void;
}) {
  if (documents.length === 0) return null;
  return (
    <div className="flex gap-2 flex-wrap">
      {documents.map((doc) => {
        const isParsing = doc.status === "parsing";
        const isError = doc.status === "error";
        const isVideo = doc.media_kind === "video";
        const frameLabel = doc.extracted_image_count
          ? ` · ${doc.extracted_image_count} khung hình`
          : "";
        const assetLabel = doc.embedded_asset_count
          ? ` · ${doc.embedded_asset_count} asset`
          : "";
        const provenanceLabel = doc.provenance_level === "page_layout"
          ? " · layout"
          : doc.provenance_level === "page_marker"
            ? " · page"
            : "";
        const label = isParsing
          ? isVideo
            ? "Wiii đang đọc video..."
            : "Wiii đang đọc..."
          : isError
            ? doc.error || "Chưa đọc được"
            : `${doc.parser || "MarkItDown"}${provenanceLabel} · ${formatBytes(doc.size_bytes)} · ${doc.char_count ?? 0} ký tự${frameLabel}${assetLabel}${doc.truncated ? " · đã rút gọn" : ""}`;
        return (
          <div
            key={doc.id}
            className={`group relative flex max-w-full items-start gap-2 rounded-xl border px-3 py-2 text-xs ${
              isError
                ? "border-red-200 bg-red-50 text-red-700"
                : "border-[var(--border)] bg-surface-secondary text-text-secondary"
            }`}
          >
            <div className="mt-0.5 shrink-0">
              {isParsing ? (
                <Loader2 size={15} className="animate-spin text-text-tertiary" />
              ) : isError ? (
                <AlertCircle size={15} />
              ) : isVideo ? (
                <Film size={15} className="text-[var(--accent)]" />
              ) : (
                <FileText size={15} className="text-[var(--accent)]" />
              )}
            </div>
            <div className="min-w-0">
              <div className="truncate font-medium">{doc.file_name}</div>
              <div className="mt-0.5 line-clamp-2 text-[11px] opacity-80">{label}</div>
            </div>
            <button
              onClick={() => onRemove(doc.id)}
              className="ml-1 shrink-0 rounded-full p-0.5 opacity-60 hover:bg-black/5 hover:opacity-100"
              aria-label={`Xóa tài liệu ${doc.file_name}`}
            >
              <X size={13} />
            </button>
          </div>
        );
      })}
    </div>
  );
}

export function ChatInput({ onSend, onCancel, editingMessage, onClearEdit, centered }: ChatInputProps) {
  const [input, setInput] = useState("");
  const [images, setImages] = useState<AttachedImage[]>([]);
  const [documents, setDocuments] = useState<AttachedDocument[]>([]);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Wiii Pointy v3.0 — `@` mention picker state. Active khi user gõ `@`
  // ở word boundary; suggestions filter theo fragment after `@`.
  const [mentionState, setMentionState] = useState<{
    active: boolean;
    fragment: string;
    atIndex: number;
    suggestions: MentionSuggestion[];
    selectedIndex: number;
  }>({
    active: false,
    fragment: "",
    atIndex: -1,
    suggestions: [],
    selectedIndex: 0,
  });
  const { isStreaming } = useChatStore();
  const { addToast } = useToastStore();
  const setInputFocused = useUIStore((s) => s.setInputFocused);

  // Set input when editing a message
  useEffect(() => {
    if (editingMessage !== null && editingMessage !== undefined) {
      setInput(editingMessage);
      if (textareaRef.current) {
        textareaRef.current.focus();
        textareaRef.current.style.height = "auto";
        textareaRef.current.style.height = Math.min(textareaRef.current.scrollHeight, 200) + "px";
      }
    }
  }, [editingMessage]);

  const handleSend = useCallback(() => {
    const trimmed = input.trim();
    if (isStreaming) return;
    const parsingDocs = documents.filter((doc) => doc.status === "parsing");
    if (parsingDocs.length > 0) {
      addToast("info", "Wiii vẫn đang đọc tài liệu, chờ mình một chút nhé.");
      return;
    }
    const readyDocs = documents
      .map(toParsedDocumentForContext)
      .filter((doc): doc is ParsedDocumentForContext => doc !== null);
    if (!trimmed && images.length === 0 && readyDocs.length === 0) return;
    const displayMessage = trimmed || "Hãy xem nội dung mình vừa đính kèm và tóm tắt những điểm quan trọng.";
    // Sprint 179 + video context: include manual images plus sampled video frames.
    const manualImageInputs: ImageInput[] = images.map(img => ({
      type: "base64" as const,
      media_type: img.media_type,
      data: img.data,
      detail: "auto" as const,
    }));
    const videoFrameInputs = toImageInputsFromExtractedFrames(
      readyDocs,
      Math.max(0, MAX_IMAGE_ATTACHMENTS - manualImageInputs.length),
    );
    const mergedImageInputs = [...manualImageInputs, ...videoFrameInputs];
    const imageInputs: ImageInput[] | undefined = mergedImageInputs.length > 0
      ? mergedImageInputs
      : undefined;
    const documentContext = buildChatDocumentContext(readyDocs);
    const documentAttachments = readyDocs.map(toDisplayDocumentAttachment);

    // Wiii Pointy v2.8 — parse `@plugin-name` mentions BEFORE send.
    // v3.0: KEEP the original text (mentions intact) so the chat-history
    // bubble can render the chip persistently. Backend force_skills
    // bypass keyword gates regardless of @-prefix in text. Backend also
    // tolerates @-tokens in the message because LLM treats them as user
    // emphasis, not commands. Pattern matches ChatGPT plugins / Cursor
    // `@codebase` — chip persist trong message bubble after send.
    const parsed = parseSkillMentions(displayMessage);
    const forceSkills = parsed.forceSkills.length > 0 ? parsed.forceSkills : undefined;

    onSend(displayMessage, imageInputs, forceSkills, documentAttachments, documentContext);
    setInput("");
    setImages([]);
    setDocuments([]);
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
      // Re-focus input after sending (Sprint 106)
      textareaRef.current.focus();
    }
  }, [input, images, documents, isStreaming, onSend, addToast]);

  // Update mention picker state dựa vào current text + caret position.
  const updateMentionState = useCallback((text: string, caretPos: number) => {
    const typing = detectMentionTyping(text, caretPos);
    if (!typing.active) {
      setMentionState((prev) =>
        prev.active
          ? { active: false, fragment: "", atIndex: -1, suggestions: [], selectedIndex: 0 }
          : prev,
      );
      return;
    }
    const suggestions = suggestMentions(typing.fragment);
    setMentionState({
      active: suggestions.length > 0,
      fragment: typing.fragment,
      atIndex: typing.atIndex,
      suggestions,
      selectedIndex: 0,
    });
  }, []);

  const closeMentionPicker = useCallback(() => {
    setMentionState({
      active: false,
      fragment: "",
      atIndex: -1,
      suggestions: [],
      selectedIndex: 0,
    });
  }, []);

  /** Replace `@<fragment>` với canonical id + space, close picker. */
  const acceptMention = useCallback(
    (suggestion: MentionSuggestion) => {
      const ta = textareaRef.current;
      if (!ta) return;
      const { atIndex } = mentionState;
      if (atIndex < 0) return;
      const before = input.slice(0, atIndex);
      const afterFragmentEnd = atIndex + 1 + mentionState.fragment.length;
      const after = input.slice(afterFragmentEnd);
      const insertion = `@${suggestion.entry.id} `;
      const newText = before + insertion + after;
      const newCaret = (before + insertion).length;
      setInput(newText);
      closeMentionPicker();
      // Restore caret position trên next paint (textarea is controlled).
      requestAnimationFrame(() => {
        if (textareaRef.current) {
          textareaRef.current.setSelectionRange(newCaret, newCaret);
          textareaRef.current.focus();
        }
      });
    },
    [input, mentionState, closeMentionPicker],
  );

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    // Wiii Pointy v3.0 — intercept keys cho mention picker.
    if (mentionState.active && mentionState.suggestions.length > 0) {
      if (e.key === "ArrowDown") {
        e.preventDefault();
        setMentionState((prev) => ({
          ...prev,
          selectedIndex: (prev.selectedIndex + 1) % prev.suggestions.length,
        }));
        return;
      }
      if (e.key === "ArrowUp") {
        e.preventDefault();
        setMentionState((prev) => ({
          ...prev,
          selectedIndex:
            (prev.selectedIndex - 1 + prev.suggestions.length) %
            prev.suggestions.length,
        }));
        return;
      }
      if (e.key === "Enter" || e.key === "Tab") {
        e.preventDefault();
        const sel = mentionState.suggestions[mentionState.selectedIndex];
        if (sel) acceptMention(sel);
        return;
      }
      if (e.key === "Escape") {
        e.preventDefault();
        closeMentionPicker();
        return;
      }
    }

    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const handleInput = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    const newText = e.target.value;
    setInput(newText);
    const el = e.target;
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, 200) + "px";
    // Wiii Pointy v3.0 — re-detect mention typing on each input change.
    updateMentionState(newText, el.selectionStart ?? newText.length);
  };

  // Update mention state khi caret di chuyển (arrow keys, click) — ngoài
  // typing event thuần để picker đóng đúng lúc user đi ra khỏi mention zone.
  const handleSelect = (e: React.SyntheticEvent<HTMLTextAreaElement>) => {
    const el = e.currentTarget;
    updateMentionState(el.value, el.selectionStart ?? el.value.length);
  };

  const removeDocument = useCallback((id: string) => {
    setDocuments((prev) => prev.filter((doc) => doc.id !== id));
  }, []);

  const attachImageFile = useCallback((file: File) => {
    if (file.size > MAX_IMAGE_SIZE_BYTES) {
      addToast("error", `"${file.name}" quá lớn (tối đa 10MB).`);
      return;
    }
    const reader = new FileReader();
    reader.onload = () => {
      const base64 = (reader.result as string).split(",")[1];
      const preview = reader.result as string;
      setImages(prev => [...prev, { data: base64, media_type: file.type, preview }]);
    };
    reader.onerror = () => addToast("error", "Không thể đọc file ảnh.");
    reader.readAsDataURL(file);
  }, [addToast]);

  const attachDocumentFile = useCallback((file: File) => {
    const mediaKind = getContextMediaKind(file);
    const maxSizeBytes = mediaKind === "video" ? MAX_VIDEO_SIZE_BYTES : MAX_DOCUMENT_SIZE_BYTES;
    const maxSizeMb = maxSizeBytes / 1024 / 1024;
    if (file.size > maxSizeBytes) {
      addToast("error", `"${file.name}" quá lớn (tối đa ${maxSizeMb}MB).`);
      return;
    }
    const id = createAttachmentId(file);
    setDocuments((prev) => [
      ...prev,
      {
        id,
        file_name: file.name,
        mime_type: file.type || null,
        media_kind: mediaKind,
        size_bytes: file.size,
        status: "parsing",
      },
    ]);
    addToast("info", `Wiii đang đọc "${file.name}"...`);
    parseDocumentContext(file)
      .then((parsed) => {
        setDocuments((prev) =>
          prev.map((doc) =>
            doc.id === id
              ? {
                  id,
                  file_name: parsed.file_name || file.name,
                  mime_type: parsed.mime_type || file.type || null,
                  media_kind: parsed.media_kind || mediaKind,
                  size_bytes: parsed.size_bytes,
                  parser: parsed.parser,
                  parser_chain: parsed.parser_chain || [],
                  parser_warning: parsed.parser_warning || null,
                  provenance_level: parsed.provenance_level,
                  char_count: parsed.char_count,
                  extracted_images: parsed.extracted_images || [],
                  extracted_image_count: parsed.extracted_image_count || 0,
                  embedded_assets: parsed.embedded_assets || [],
                  embedded_asset_count: parsed.embedded_asset_count || 0,
                  figure_count: parsed.figure_count || 0,
                  table_count: parsed.table_count || 0,
                  section_snippets: parsed.section_snippets || [],
                  truncated: parsed.truncated,
                  markdown: parsed.markdown,
                  status: "ready",
                }
              : doc,
          ),
        );
        addToast("success", `Đã đọc xong "${file.name}".`);
      })
      .catch((err) => {
        setDocuments((prev) =>
          prev.map((doc) =>
            doc.id === id
              ? { ...doc, status: "error", error: getReadableError(err) }
              : doc,
          ),
        );
        addToast("error", `Chưa đọc được "${file.name}".`);
      });
  }, [addToast]);

  const handlePaste = (e: React.ClipboardEvent) => {
    const items = e.clipboardData.items;
    for (const item of items) {
      if (item.type.startsWith("image/")) {
        e.preventDefault();
        const file = item.getAsFile();
        if (!file || images.length >= MAX_IMAGE_ATTACHMENTS) {
          if (images.length >= MAX_IMAGE_ATTACHMENTS) addToast("info", "Tối đa 5 ảnh mỗi tin nhắn.");
          return;
        }
        // Security: enforce 10MB file size limit
        if (file.size > MAX_IMAGE_SIZE_BYTES) {
          addToast("error", "Ảnh quá lớn (tối đa 10MB).");
          return;
        }
        const reader = new FileReader();
        reader.onload = () => {
          const base64 = (reader.result as string).split(",")[1];
          const preview = reader.result as string;
          setImages(prev => [...prev, { data: base64, media_type: file.type, preview }]);
        };
        reader.onerror = () => addToast("error", "Không thể đọc ảnh từ clipboard.");
        reader.readAsDataURL(file);
        return;
      }
    }
  };

  const handleAttach = () => {
    const input = document.createElement("input");
    input.type = "file";
    input.accept = ATTACH_ACCEPT;
    input.multiple = true;
    input.onchange = (e) => {
      const files = (e.target as HTMLInputElement).files;
      if (!files) return;
      let imageSlots = MAX_IMAGE_ATTACHMENTS - images.length;
      let documentSlots = MAX_DOCUMENT_ATTACHMENTS - documents.length;
      Array.from(files).forEach(file => {
        if (file.type.startsWith("image/")) {
          if (imageSlots <= 0) {
            addToast("info", "Tối đa 5 ảnh mỗi tin nhắn.");
            return;
          }
          imageSlots -= 1;
          attachImageFile(file);
          return;
        }
        if (isSupportedDocumentFile(file)) {
          if (documentSlots <= 0) {
            addToast("info", "Tối đa 3 file tài liệu/video mỗi tin nhắn.");
            return;
          }
          documentSlots -= 1;
          attachDocumentFile(file);
          return;
        }
        addToast("error", `"${file.name}" chưa thuộc định dạng Wiii đọc được.`);
      });
    };
    input.click();
  };

  // eslint-disable-next-line react-hooks/exhaustive-deps
  const welcomePlaceholder = useMemo(() => getWelcomePlaceholder(), []);

  const charCount = input.length;
  const showCharCount = charCount > MAX_MESSAGE_LENGTH * 0.8;
  const isNearLimit = charCount > MAX_MESSAGE_LENGTH * 0.95;
  const hasReadyDocuments = documents.some((doc) => doc.status === "ready");
  const hasParsingDocuments = documents.some((doc) => doc.status === "parsing");
  const canSend = !isStreaming && !hasParsingDocuments && Boolean(input.trim() || images.length > 0 || hasReadyDocuments);

  // Centered (welcome) mode: Claude F12 exact — floating card, m-3.5 inner
  if (centered) {
    return (
      <div className="w-full">
        <div className="input-card">
          <div className="m-3.5 flex flex-col gap-3">
            <CapabilityStatusBar compact />
            {/* Sprint 179: Image preview strip */}
            {images.length > 0 && (
              <div className="flex gap-2 flex-wrap">
                {images.map((img, i) => (
                  <div key={`img-${img.data.substring(0, 16)}`} className="relative group">
                    <img src={img.preview} alt={`Ảnh đính kèm ${i + 1}`} className="w-16 h-16 object-cover rounded-lg border border-[var(--border)]" />
                    <button
                      onClick={() => setImages(prev => prev.filter((_, idx) => idx !== i))}
                      className="absolute -top-1.5 -right-1.5 w-5 h-5 bg-red-500 text-white rounded-full text-xs flex items-center justify-center opacity-0 group-hover:opacity-100 focus-visible:opacity-100 transition-opacity"
                      aria-label={`Xoá ảnh ${i + 1}`}
                    >
                      &times;
                    </button>
                  </div>
                ))}
              </div>
            )}
            <DocumentAttachmentStrip documents={documents} onRemove={removeDocument} />
            {/* Textarea — min-h-[3rem], max-h-96 */}
            <div className="relative">
              <MentionMirror
                text={input}
                className="w-full pl-1.5 pt-1.5 text-[16px] leading-[1.6]"
              />
              <textarea
                ref={textareaRef}
                value={input}
                onChange={handleInput}
                onKeyDown={handleKeyDown}
                onSelect={handleSelect}
                onPaste={handlePaste}
                onFocus={() => setInputFocused(true)}
                onBlur={() => setInputFocused(false)}
                placeholder={welcomePlaceholder}
                className="relative w-full resize-none bg-transparent pl-1.5 pt-1.5 text-[16px] leading-[1.6] text-text placeholder:text-text-tertiary placeholder:italic focus:outline-none min-h-[3rem] max-h-96"
                rows={2}
                maxLength={MAX_MESSAGE_LENGTH}
                disabled={isStreaming}
                aria-label="Khung soạn tin nhắn"
                data-wiii-id="chat-textarea"
              />
              {mentionState.active && (
                <MentionPicker
                  suggestions={mentionState.suggestions}
                  selectedIndex={mentionState.selectedIndex}
                  fragment={mentionState.fragment}
                  onSelect={acceptMention}
                  onHover={(i) =>
                    setMentionState((prev) => ({ ...prev, selectedIndex: i }))
                  }
                />
              )}
            </div>
            {/* Toolbar: attach + domain | char count + send */}
            <div className="flex items-center justify-between h-8">
              <div className="flex items-center gap-2">
                <button
                  onClick={handleAttach}
                  className="flex items-center justify-center w-8 h-8 rounded-md text-text-tertiary hover:text-text-secondary hover:bg-surface-tertiary active:scale-95 transition-all duration-300"
                  style={{ border: "0.5px solid var(--border)" }}
                  title="Đính kèm ảnh, tài liệu hoặc video"
                  aria-label="Đính kèm ảnh, tài liệu hoặc video"
                  data-wiii-id="attach-file-button"
                  data-wiii-synonyms="đính kèm file,kẹp giấy,paperclip,upload,attachment,image attachment,thêm ảnh,thêm file"
                >
                  <Paperclip size={16} />
                </button>
                <DomainSelector compact />
                <ModelSelector compact />
                <PointyModeToggle />
              </div>
              <div className="flex items-center gap-2">
                {showCharCount && (
                  <span
                    className={`text-[10px] tabular-nums ${
                      isNearLimit ? "text-red-500" : "text-text-tertiary"
                    }`}
                  >
                    {charCount}/{MAX_MESSAGE_LENGTH}
                  </span>
                )}
                <span
                  className="inline-flex w-8 h-8"
                >
                  {isStreaming ? (
                    <button
                      onClick={onCancel}
                      className="flex items-center justify-center w-8 h-8 rounded-lg bg-red-500/90 text-white hover:bg-red-600 active:scale-95 transition-all duration-300"
                      title="Dừng"
                      aria-label="Dừng tạo phản hồi"
                      data-wiii-id="chat-stop-button"
                    >
                      <Square size={13} />
                    </button>
                  ) : (
                    <button
                      onClick={handleSend}
                      disabled={!canSend}
                      className="flex items-center justify-center w-8 h-8 rounded-lg bg-[var(--accent)] text-white hover:bg-[var(--accent-hover)] disabled:opacity-40 disabled:cursor-not-allowed active:scale-[0.985] transition-all duration-300"
                      style={{ transitionTimingFunction: "cubic-bezier(0.165, 0.85, 0.45, 1)" }}
                      title="Gửi (Enter)"
                      aria-label="Gửi tin nhắn"
                      data-wiii-id="chat-send-button"
                      data-wiii-synonyms="nút gửi,nút gửi tin nhắn,send button"
                    >
                      <ArrowUp size={16} strokeWidth={2.5} />
                    </button>
                  )}
                </span>
              </div>
            </div>
          </div>
        </div>
      </div>
    );
  }

  // Normal bottom-bar mode — input-card style (Sprint 162)
  return (
    <div className="chat-composer-shell px-4 py-3">
      <div className="chat-lane">
        <CapabilityStatusBar />
        {/* Edit mode banner */}
        {editingMessage && onClearEdit && (
          <div className="flex items-center gap-2 mb-2 px-3 py-1.5 rounded-lg bg-[var(--accent-light)] text-[var(--accent)] text-xs">
            <span className="flex-1">Chỉnh sửa tin nhắn</span>
            <button
              onClick={() => {
                onClearEdit();
                setInput("");
              }}
              className="p-0.5 rounded hover:bg-[var(--accent)]/10"
              aria-label="Huỷ chỉnh sửa"
            >
              <X size={14} />
            </button>
          </div>
        )}

        <div className="input-card">
          <div className="m-3 flex flex-col gap-2">
            {/* Sprint 179: Image preview strip */}
            {images.length > 0 && (
              <div className="flex gap-2 flex-wrap">
                {images.map((img, i) => (
                  <div key={`img-${img.data.substring(0, 16)}`} className="relative group">
                    <img src={img.preview} alt={`Ảnh đính kèm ${i + 1}`} className="w-16 h-16 object-cover rounded-lg border border-[var(--border)]" />
                    <button
                      onClick={() => setImages(prev => prev.filter((_, idx) => idx !== i))}
                      className="absolute -top-1.5 -right-1.5 w-5 h-5 bg-red-500 text-white rounded-full text-xs flex items-center justify-center opacity-0 group-hover:opacity-100 focus-visible:opacity-100 transition-opacity"
                      aria-label={`Xoá ảnh ${i + 1}`}
                    >
                      &times;
                    </button>
                  </div>
                ))}
              </div>
            )}
            <DocumentAttachmentStrip documents={documents} onRemove={removeDocument} />
            <div className="relative">
              <MentionMirror
                text={input}
                className="w-full px-1.5 pt-1 text-[14px]"
              />
              <textarea
                ref={textareaRef}
                value={input}
                onChange={handleInput}
                onKeyDown={handleKeyDown}
                onSelect={handleSelect}
                onPaste={handlePaste}
                onFocus={() => setInputFocused(true)}
                onBlur={() => setInputFocused(false)}
                placeholder="Hỏi Wiii bất cứ điều gì..."
                className="relative w-full resize-none bg-transparent px-1.5 pt-1 text-[14px] text-text placeholder:text-text-tertiary focus:outline-none min-h-[2.5rem] max-h-48"
                rows={1}
                maxLength={MAX_MESSAGE_LENGTH}
                disabled={isStreaming}
                aria-label="Khung soạn tin nhắn"
                data-wiii-id="chat-textarea"
              />
              {mentionState.active && (
                <MentionPicker
                  suggestions={mentionState.suggestions}
                  selectedIndex={mentionState.selectedIndex}
                  fragment={mentionState.fragment}
                  onSelect={acceptMention}
                  onHover={(i) =>
                    setMentionState((prev) => ({ ...prev, selectedIndex: i }))
                  }
                />
              )}
            </div>
            <div className="flex items-center justify-between h-8">
              <div className="flex items-center gap-3">
                <button
                  onClick={handleAttach}
                  className="flex items-center justify-center w-7 h-7 rounded-md text-text-tertiary hover:text-text-secondary hover:bg-surface-tertiary active:scale-95 transition-all duration-300"
                  style={{ border: "0.5px solid var(--border)" }}
                  title="Đính kèm ảnh, tài liệu hoặc video"
                  aria-label="Đính kèm ảnh, tài liệu hoặc video"
                  data-wiii-id="attach-file-button"
                  data-wiii-synonyms="đính kèm file,kẹp giấy,paperclip,upload,attachment,image attachment,thêm ảnh,thêm file"
                >
                  <Paperclip size={14} />
                </button>
                <DomainSelector />
                <ModelSelector />
                <PointyModeToggle />
                <span className="text-[10px] text-text-tertiary">
                  Enter gửi · Shift+Enter xuống dòng
                </span>
              </div>
              <div className="flex items-center gap-2">
                {showCharCount && (
                  <span
                    className={`text-[10px] tabular-nums ${
                      isNearLimit ? "text-red-500" : "text-text-tertiary"
                    }`}
                  >
                    {charCount}/{MAX_MESSAGE_LENGTH}
                  </span>
                )}
                <span
                  className="inline-flex w-8 h-8"
                >
                  {isStreaming ? (
                    <button
                      onClick={onCancel}
                      className="flex items-center justify-center w-8 h-8 rounded-lg bg-red-500/90 text-white hover:bg-red-600 active:scale-95 transition-all duration-300"
                      title="Dừng"
                      aria-label="Dừng tạo phản hồi"
                      data-wiii-id="chat-stop-button"
                    >
                      <Square size={13} />
                    </button>
                  ) : (
                    <button
                      onClick={handleSend}
                      disabled={!canSend}
                      className="flex items-center justify-center w-8 h-8 rounded-lg bg-[var(--accent)] text-white hover:bg-[var(--accent-hover)] disabled:opacity-40 disabled:cursor-not-allowed active:scale-[0.98] transition-all duration-150"
                      title="Gửi (Enter)"
                      aria-label="Gửi tin nhắn"
                      data-wiii-id="chat-send-button"
                      data-wiii-synonyms="nút gửi,nút gửi tin nhắn,send button"
                    >
                      <ArrowUp size={15} strokeWidth={2.5} />
                    </button>
                  )}
                </span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
