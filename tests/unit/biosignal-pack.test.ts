import { describe, expect, it, vi } from "vitest";
import {
  parseBiosignalPackCatalog,
  readBiosignalPackCatalog,
  resolveBiosignalInstallPlan,
} from "../../src/skills/biosignal-pack.js";
import { readRecommendedCatalog } from "../../src/skills/recommended.js";
import { BiosignalWizardComponent } from "../../src/tui/biosignal-wizard.js";

const sampleCatalog = parseBiosignalPackCatalog({
  schemaVersion: "psyclaw/biosignal-pack/v1",
  documentVersion: "0.1.0",
  domains: [
    {
      id: "eeg-erp",
      name: "EEG / ERP",
      description: "ERP",
      mcp: ["mne-mcp"],
      skills: ["mne-analyst", "mne-erp"],
    },
    {
      id: "ecg-hrv",
      name: "ECG / HRV",
      description: "HRV",
      mcp: [],
      skills: ["neurokit2"],
    },
    {
      id: "bids",
      name: "BIDS",
      description: "BIDS",
      mcp: [],
      skills: ["bids"],
    },
  ],
});

describe("biosignal pack resolver", () => {
  it("dedupes mcp and skills across selected domains", () => {
    const plan = resolveBiosignalInstallPlan(sampleCatalog, ["eeg-erp", "ecg-hrv", "bids"]);
    expect(plan.domainIds).toEqual(["eeg-erp", "ecg-hrv", "bids"]);
    expect(plan.mcpIds).toEqual(["mne-mcp"]);
    expect(plan.skillIds).toEqual(["mne-analyst", "mne-erp", "neurokit2", "bids"]);
  });

  it("rejects empty or unknown domain selection", () => {
    expect(() => resolveBiosignalInstallPlan(sampleCatalog, [])).toThrow(/至少选择一个/);
    expect(() => resolveBiosignalInstallPlan(sampleCatalog, ["nope"])).toThrow(/未知研究域/);
  });

  it("ships a pack whose skill ids exist in the recommended catalog", async () => {
    const pack = await readBiosignalPackCatalog();
    const catalog = await readRecommendedCatalog();
    const skillIds = new Set(catalog.items.filter((item) => item.kind === "skill").map((item) => item.id));
    for (const domain of pack.domains) {
      for (const skillId of domain.skills) {
        expect(skillIds.has(skillId), `${domain.id} → ${skillId}`).toBe(true);
      }
    }
  });
});

describe("BiosignalWizardComponent", () => {
  function createWizard() {
    const results: Array<{ type: string; domainIds?: string[] }> = [];
    const tui = { requestRender: vi.fn() };
    const theme = {
      bold: (text: string) => text,
      fg: (_color: string, text: string) => text,
    };
    const keybindings = {
      matches: (data: string, binding: string) => (
        (binding === "tui.select.up" && data === "UP") ||
        (binding === "tui.select.down" && data === "DOWN") ||
        (binding === "tui.select.confirm" && data === "ENTER") ||
        (binding === "tui.select.cancel" && data === "ESC")
      ),
    };
    const component = new BiosignalWizardComponent(
      sampleCatalog.domains.map((domain) => ({
        id: domain.id,
        name: domain.name,
        description: domain.description,
      })),
      (domainIds) => {
        const plan = resolveBiosignalInstallPlan(sampleCatalog, domainIds);
        return {
          domainNames: plan.domainNames,
          mcpIds: plan.mcpIds,
          skillIds: plan.skillIds,
        };
      },
      tui as never,
      theme as never,
      keybindings as never,
      (result) => results.push(result),
    );
    return { component, results, tui };
  }

  it("requires a selection before advancing", () => {
    const { component } = createWizard();
    component.handleInput("ENTER");
    const text = component.render(80).join("\n");
    expect(text).toContain("请先用 Space");
  });

  it("confirms selected domains after plan review", () => {
    const { component, results } = createWizard();
    component.handleInput(" ");
    component.handleInput("ENTER");
    expect(component.render(100).join("\n")).toContain("确认安装清单");
    expect(component.render(100).join("\n")).toContain("mne-mcp");
    component.handleInput("ENTER");
    expect(results).toEqual([{ type: "confirm", domainIds: ["eeg-erp"] }]);
  });

  it("returns to selection on Esc from confirm", () => {
    const { component, results } = createWizard();
    component.handleInput(" ");
    component.handleInput("ENTER");
    component.handleInput("ESC");
    expect(component.render(80).join("\n")).toContain("选择研究域");
    expect(results).toEqual([]);
  });
});
