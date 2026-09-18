import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import ChallengeBody, { resolveArtifact } from "./ChallengeBody";
import type { Artifact } from "../api/challenges";

function artifact(overrides: Partial<Artifact> = {}): Artifact {
  return {
    id: "a1",
    filename: "topology.png",
    content_type: "image/png",
    size_bytes: 1024,
    checksum_sha256: "abc",
    ...overrides,
  };
}

const urlFor = (id: string) => `/api/challenges/c1/artifacts/${id}`;

describe("ChallengeBody", () => {
  it("renders a fenced code block as a pre, not as backticks", () => {
    const { container } = render(
      <ChallengeBody>{'Look:\n\n```json\n{"a": 1}\n```'}</ChallengeBody>,
    );

    // This is already how a description in the working CSV is written; it used
    // to render the backticks literally.
    const pre = container.querySelector("pre");
    expect(pre).not.toBeNull();
    expect(pre!.textContent).toContain('{"a": 1}');
    expect(container.textContent).not.toContain("```");
  });

  it("renders raw HTML as text, never as markup", () => {
    const { container } = render(
      <ChallengeBody>{'<script>alert(1)</script> and <b>bold</b>'}</ChallengeBody>,
    );

    // rehype-raw is off, and stays off — the rule is unconditional even though
    // a challenge body is trusted input.
    expect(container.querySelector("script")).toBeNull();
    expect(container.querySelector("b")).toBeNull();
    expect(container.textContent).toContain("<b>bold</b>");
  });

  it("renders a plain paragraph exactly as before", () => {
    render(<ChallengeBody>What port does encrypted web traffic use?</ChallengeBody>);

    expect(
      screen.getByText("What port does encrypted web traffic use?"),
    ).toBeInTheDocument();
  });

  describe("artifact references", () => {
    it("resolves an image to its download URL", () => {
      render(
        <ChallengeBody artifacts={[artifact()]} urlFor={urlFor}>
          {"![The network](artifact:topology.png)"}
        </ChallengeBody>,
      );

      expect(screen.getByAltText("The network")).toHaveAttribute(
        "src",
        "/api/challenges/c1/artifacts/a1",
      );
    });

    it("resolves a link to any other file", () => {
      render(
        <ChallengeBody
          artifacts={[artifact({ id: "a2", filename: "dump.pcap", content_type: "application/vnd.tcpdump.pcap" })]}
          urlFor={urlFor}
        >
          {"Start with [the capture](artifact:dump.pcap)."}
        </ChallengeBody>,
      );

      // Offered where it is mentioned rather than in a list below (§9.1).
      const link = screen.getByRole("link", { name: "the capture" });
      expect(link).toHaveAttribute("href", "/api/challenges/c1/artifacts/a2");
      expect(link).toHaveAttribute("download");
    });

    it("degrades to alt text when nothing matches", () => {
      render(
        <ChallengeBody artifacts={[artifact()]} urlFor={urlFor}>
          {"![A diagram that is missing](artifact:nope.png)"}
        </ChallengeBody>,
      );

      // A gap in the prose, not a broken-image icon that reads as the platform
      // falling over.
      expect(screen.getByText("A diagram that is missing")).toBeInTheDocument();
      expect(screen.queryByRole("img")).not.toBeInTheDocument();
    });

    it("leaves an ordinary external link alone", () => {
      render(
        <ChallengeBody artifacts={[]} urlFor={urlFor}>
          {"See [the docs](https://example.test/x)."}
        </ChallengeBody>,
      );

      const link = screen.getByRole("link", { name: "the docs" });
      expect(link).toHaveAttribute("href", "https://example.test/x");
      expect(link).not.toHaveAttribute("download");
    });

    it("matches on filename rather than id", () => {
      // An author types this before any upload exists, so a UUID is not a thing
      // they could write (spec 063 §3).
      expect(
        resolveArtifact("artifact:topology.png", [artifact()], urlFor),
      ).toBe("/api/challenges/c1/artifacts/a1");
      expect(resolveArtifact("artifact:a1", [artifact()], urlFor)).toBeNull();
    });

    it("takes the first of two files sharing a name", () => {
      const first = artifact({ id: "first" });
      const second = artifact({ id: "second" });

      expect(resolveArtifact("artifact:topology.png", [first, second], urlFor)).toBe(
        "/api/challenges/c1/artifacts/first",
      );
    });

    it("ignores a href that is not a reference", () => {
      expect(resolveArtifact("https://example.test", [artifact()], urlFor)).toBeNull();
      expect(resolveArtifact(undefined, [artifact()], urlFor)).toBeNull();
    });
  });
});
