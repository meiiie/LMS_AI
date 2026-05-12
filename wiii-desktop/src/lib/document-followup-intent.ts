function normalizePromptIntent(text: string): string {
  return (text || "")
    .normalize("NFD")
    .replace(/\p{Diacritic}/gu, "")
    .toLowerCase()
    .trim();
}

export function looksDocumentContextFollowupIntent(prompt: string): boolean {
  const normalized = normalizePromptIntent(prompt);
  if (!normalized) return false;
  return (
    /(^|[\s,.;:!?])(preview|draft|outline|syllabus)($|[\s,.;:!?])/.test(normalized)
    || normalized.includes("xem truoc")
    || normalized.includes("ban xem truoc")
    || normalized.includes("ban nhap")
    || normalized.includes("tao bai giang")
    || normalized.includes("soan bai giang")
    || normalized.includes("lap bai giang")
    || normalized.includes("xay dung bai giang")
    || normalized.includes("thiet ke bai giang")
    || normalized.includes("tao giao an")
    || normalized.includes("soan giao an")
    || normalized.includes("tao hoc lieu")
    || normalized.includes("tao khoa hoc")
    || normalized.includes("thiet ke khoa hoc")
    || normalized.includes("chia thanh chuong")
    || normalized.includes("chia thanh bai")
    || normalized.includes("chuong trinh dao tao")
    || normalized.includes("ke hoach giang day")
    || normalized.includes("lo trinh hoc")
    || normalized.includes("source reference")
    || normalized.includes("source_references")
    || normalized.includes("citation")
    || normalized.includes("trich dan")
    || normalized.includes("nguon doi chieu")
  );
}
