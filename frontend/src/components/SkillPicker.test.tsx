import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import SkillPicker from "./SkillPicker";
import type { Skill } from "../api/adminSkills";

function skill(id: string, name: string, kind: "useful" | "funny", category: string | null): Skill {
  return { id, name, kind, category_id: category, display_order: 0, description: null };
}

const SKILLS: Skill[] = [
  skill("s1", "Zebra Wrangling", "useful", "other"),
  skill("s2", "Injection Artistry", "useful", "web"),
  skill("s3", "Reflexive Inspect Element", "funny", "web"),
  skill("s4", "Aardvark Counting", "funny", "other"),
];

describe("SkillPicker", () => {
  it("sorts this category's skills to the top, useful before funny", () => {
    render(
      <SkillPicker skills={SKILLS} categoryId="web" selected={[]} onChange={vi.fn()} />,
    );

    const labels = screen
      .getAllByRole("checkbox")
      .map((box) => box.closest("label")!.textContent ?? "");

    // This category first (useful, then funny), then everything else A-Z.
    expect(labels[0]).toContain("Injection Artistry");
    expect(labels[1]).toContain("Reflexive Inspect Element");
    expect(labels[2]).toContain("Zebra Wrangling");
  });

  it("lets any skill be chosen, not just this category's", async () => {
    const onChange = vi.fn();
    render(
      <SkillPicker skills={SKILLS} categoryId="web" selected={[]} onChange={onChange} />,
    );

    await userEvent.click(screen.getByText("Zebra Wrangling"));

    expect(onChange).toHaveBeenCalledWith(["s1"]);
  });

  it("searches across every skill", async () => {
    render(
      <SkillPicker skills={SKILLS} categoryId="web" selected={[]} onChange={vi.fn()} />,
    );

    await userEvent.type(screen.getByLabelText("Search skills"), "aardvark");

    expect(screen.getByText("Aardvark Counting")).toBeInTheDocument();
    expect(screen.queryByText("Injection Artistry")).not.toBeInTheDocument();
  });

  it("toggles a chosen skill back off", async () => {
    const onChange = vi.fn();
    render(
      <SkillPicker skills={SKILLS} categoryId="web" selected={["s2"]} onChange={onChange} />,
    );

    await userEvent.click(screen.getByText("Injection Artistry"));

    expect(onChange).toHaveBeenCalledWith([]);
  });
});
