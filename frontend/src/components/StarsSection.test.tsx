import { screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import StarsSection from "./StarsSection";
import { renderApp, stubFetch } from "../test/utils";

afterEach(() => {
  vi.unstubAllGlobals();
});

const STARS = [
  {
    challenge_id: "c1",
    challenge_title: "The Prompt Injection",
    zone_name: "AI/LLM Security",
    tier: "floor",
    level: 6,
  },
  {
    challenge_id: "c2",
    challenge_title: "Cookie Jar",
    zone_name: "Web Attacks",
    tier: "neighborhood",
    level: 1,
  },
];

function render(body: unknown = STARS) {
  stubFetch((path) => {
    if (path.endsWith("/character/stars")) return { status: 200, body };
    return { status: 200, body: {} };
  });
  renderApp(<StarsSection />);
}

describe("StarsSection", () => {
  it("lists the bosses felled with a star count", async () => {
    render();

    expect(await screen.findByText("Bosses felled")).toBeInTheDocument();
    expect(screen.getByText("2 stars")).toBeInTheDocument();
    expect(screen.getByText("The Prompt Injection")).toBeInTheDocument();
  });

  it("names the tier rather than relying on colour alone", async () => {
    render();

    // Colour cannot be the only thing carrying the meaning — this has to read
    // in greyscale and to a screen reader.
    expect(
      await screen.findByText("Floor Boss · AI/LLM Security"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Neighborhood Boss · Web Attacks"),
    ).toBeInTheDocument();
  });

  it("stays out of the way when no boss has been beaten", () => {
    render([]);

    expect(screen.queryByText("Bosses felled")).not.toBeInTheDocument();
  });

  it("survives a partial response rather than taking the sheet down", () => {
    render({});

    expect(screen.queryByText("Bosses felled")).not.toBeInTheDocument();
  });
});
