import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { SourceCitation } from "@/components/chat/SourceCitation";

describe("SourceCitation", () => {
  it("renders web sources as a compact collapsed source box", () => {
    render(
      <SourceCitation
        sources={[
          {
            title: "Weather Hải Phòng today",
            content: "Cloudy and warm.",
            url: "https://weather.example/hai-phong",
            source_type: "web",
          },
          {
            title: "Local forecast",
            content: "Rain chance later.",
            url: "https://meteo.example/forecast",
            source_type: "web",
          },
        ]}
      />,
    );

    expect(screen.getByText("2 nguồn web")).toBeTruthy();
    expect(screen.getByTestId("web-source-citation")).toBeTruthy();
    expect(screen.getByTestId("web-source-citation-summary")).toBeTruthy();
    expect(screen.getByText("weather.example, meteo.example")).toBeTruthy();
    expect(screen.queryByText("Weather Hải Phòng today")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: /2 nguồn web/i }));

    expect(screen.getByText("Weather Hải Phòng today")).toBeTruthy();
    expect(screen.getByText("Local forecast")).toBeTruthy();
    expect(screen.getByRole("link", { name: /Weather Hải Phòng today/i }))
      .toHaveProperty("href", "https://weather.example/hai-phong");
  });

  it("keeps mixed web and uploaded document sources in the normal citation list", () => {
    render(
      <SourceCitation
        sources={[
          {
            title: "Weather source",
            content: "Cloudy and warm.",
            url: "https://weather.example/hai-phong",
            source_type: "web",
          },
          {
            title: "Uploaded forecast PDF",
            content: "Local forecast excerpt.",
            page_number: 4,
            source_type: "document",
          },
        ]}
      />,
    );

    expect(screen.queryByTestId("web-source-citation")).toBeNull();
    expect(screen.getByText("Uploaded forecast PDF")).toBeTruthy();
    expect(screen.getByRole("link", { name: /Weather source/i }))
      .toHaveProperty("href", "https://weather.example/hai-phong");
  });

  it("does not render unsafe source URLs as links", () => {
    render(
      <SourceCitation
        sources={[
          {
            title: "Unsafe web source",
            content: "Do not navigate.",
            url: "javascript:alert(1)",
            source_type: "web",
          },
        ]}
      />,
    );

    fireEvent.click(screen.getByTestId("web-source-citation-summary"));

    expect(screen.getByText("Unsafe web source")).toBeTruthy();
    expect(screen.queryByRole("link", { name: /Unsafe web source/i })).toBeNull();
  });
});
