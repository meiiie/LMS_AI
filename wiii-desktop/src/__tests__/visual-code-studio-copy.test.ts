import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const visualUiFiles = [
  "src/components/layout/CodeStudioPanel.tsx",
  "src/components/chat/VisualBlock.tsx",
  "src/components/common/InlineVisualFrame.tsx",
];

const mojibakeMarkers = [
  { label: "UTF-8 C3 decoded as Latin-1", value: "\u00c3" },
  { label: "UTF-8 C4 decoded as Latin-1", value: "\u00c4" },
  { label: "Vietnamese tone marker decoded as Latin-1", value: "\u00e1\u00ba" },
  { label: "Vietnamese vowel marker decoded as Latin-1", value: "\u00c6" },
  { label: "middle dot decoded as Latin-1", value: "\u00c2\u00b7" },
  { label: "em dash decoded as Latin-1", value: "\u00e2\u0080\u0094" },
  { label: "em dash decoded as Windows-1252", value: "\u00e2\u20ac\u201d" },
  { label: "arrow decoded as Latin-1", value: "\u00e2\u0086\u0092" },
];

describe("visual and Code Studio copy", () => {
  it.each(visualUiFiles)(
    "keeps %s free of common mojibake markers",
    (file) => {
      const content = readFileSync(join(process.cwd(), file), "utf8");

      for (const marker of mojibakeMarkers) {
        expect(content, marker.label).not.toContain(marker.value);
      }
    },
  );
});
