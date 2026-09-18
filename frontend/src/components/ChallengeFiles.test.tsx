import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import ChallengeFiles, { referenceFor } from "./ChallengeFiles";
import type { Artifact } from "../api/challenges";
import { me, renderApp, stubFetch } from "../test/utils";

afterEach(() => {
  vi.unstubAllGlobals();
});

function artifact(overrides: Partial<Artifact> = {}): Artifact {
  return {
    id: "a1",
    filename: "topology.png",
    content_type: "image/png",
    size_bytes: 2048,
    checksum_sha256: "abc",
    ...overrides,
  };
}

function render(artifacts: Artifact[], onInsert = vi.fn()) {
  const mock = stubFetch((path) => {
    if (path.endsWith("/auth/me")) return { status: 200, body: me() };
    if (path.includes("/artifacts")) {
      return { status: 201, body: artifact({ id: "new", filename: "added.png" }) };
    }
    return { status: 200, body: {} };
  });
  renderApp(<ChallengeFiles challengeId="c1" artifacts={artifacts} onInsert={onInsert} />);
  return { mock, onInsert };
}

describe("referenceFor", () => {
  it("embeds an image and links anything else", () => {
    // The same resolver answers both, so the syntax is the only difference
    // (spec 063 §9.1).
    expect(referenceFor(artifact())).toBe("![topology](artifact:topology.png)");
    expect(
      referenceFor(artifact({ filename: "dump.pcap", content_type: "application/octet-stream" })),
    ).toBe("[dump](artifact:dump.pcap)");
  });
});

describe("ChallengeFiles", () => {
  it("shows the reference an author would otherwise have no way to know", async () => {
    render([artifact()]);

    expect(await screen.findByText("![topology](artifact:topology.png)")).toBeInTheDocument();
  });

  it("uploads a file", async () => {
    const { mock } = render([]);

    const file = new File(["png bytes"], "added.png", { type: "image/png" });
    await userEvent.upload(screen.getByLabelText("Upload a file"), file);

    await waitFor(() => {
      const call = mock.mock.calls.find(([path]) => String(path).includes("/artifacts"));
      expect(call).toBeTruthy();
      // FormData, not JSON — the browser writes its own multipart boundary.
      expect(call?.[1]?.body).toBeInstanceOf(FormData);
    });
  });

  it("inserts a reference rather than only offering it", async () => {
    const onInsert = vi.fn();
    render([artifact()], onInsert);

    await userEvent.click(await screen.findByRole("button", { name: "Insert" }));

    expect(onInsert).toHaveBeenCalledWith("![topology](artifact:topology.png)");
  });

  it("copies a reference to the clipboard", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    vi.stubGlobal("navigator", { ...navigator, clipboard: { writeText } });
    render([artifact()]);

    await userEvent.click(await screen.findByRole("button", { name: "Copy" }));

    expect(writeText).toHaveBeenCalledWith("![topology](artifact:topology.png)");
  });

  it("survives a clipboard it is not allowed to use", async () => {
    const writeText = vi.fn().mockRejectedValue(new Error("denied"));
    vi.stubGlobal("navigator", { ...navigator, clipboard: { writeText } });
    render([artifact()]);

    await userEvent.click(await screen.findByRole("button", { name: "Copy" }));

    // Insert still works, and the reference is on screen to be typed.
    expect(screen.getByText("![topology](artifact:topology.png)")).toBeInTheDocument();
  });

  it("flags two files sharing a name", async () => {
    render([artifact({ id: "first" }), artifact({ id: "second" })]);

    // A reference resolves to the first, and this is the moment that can be
    // fixed (spec 063 §3).
    expect((await screen.findAllByText(/Another file has this name/)).length).toBe(2);
  });

  it("says what the panel is for when it is empty", async () => {
    render([]);

    expect(await screen.findByText(/None yet/)).toBeInTheDocument();
  });
});
