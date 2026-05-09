import { describe, expect, it } from "vitest";
import {
  stripWiiiInternalMarkup,
  stripWiiiInternalMarkupFromStream,
} from "@/lib/internal-markup";

describe("Wiii internal markup sanitizer", () => {
  it("strips soul metadata comments before rendering", () => {
    expect(
      stripWiiiInternalMarkup(
        '<!--WIII_SOUL: {"mood":"warm"}--> Nut gui tin nhan.',
      ),
    ).toBe("Nut gui tin nhan.");
    expect(
      stripWiiiInternalMarkup(
        '<! -- WIII_SOUL: {"mood":"warm"} -- > Nut gui tin nhan.',
      ),
    ).toBe("Nut gui tin nhan.");
    expect(
      stripWiiiInternalMarkup(
        '&lt;!-- WIII_SOUL: {"mood":"warm"} --&gt; Nut gui tin nhan.',
      ),
    ).toBe("Nut gui tin nhan.");
  });

  it("buffers soul metadata comments that are split across stream chunks", () => {
    const first = stripWiiiInternalMarkupFromStream(
      '<! --WIII_SOUL: {"mood":"warm"',
    );
    expect(first.content).toBe("");
    expect(first.pending).toContain("WIII_SOUL");

    const second = stripWiiiInternalMarkupFromStream(
      "}--> Nut gui tin nhan.",
      first.pending,
    );
    expect(second.content).toBe("Nut gui tin nhan.");
    expect(second.pending).toBe("");
  });

  it("does not strip ordinary HTML comments", () => {
    const content = "<!-- regular note --> Noi dung that.";
    expect(stripWiiiInternalMarkup(content)).toBe(content);
  });
});
