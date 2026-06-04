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
});
