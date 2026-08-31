import { describe, expect, it, vi } from "vitest";
import { SkillManagerComponent, type SkillManagerAction, type SkillManagerItem } from "../../src/tui/skill-manager.js";

const items: SkillManagerItem[] = [
  { id: "core:research-intake", name: "research-intake", description: "Core", status: "core" },
  { id: "enabled", name: "Enabled", description: "Enabled Skill", status: "enabled" },
  { id: "disabled", name: "Disabled", description: "Disabled Skill", status: "disabled" },
  { id: "missing", name: "Missing", description: "Missing Skill", status: "missing", sourceRef: "https://example.test" },
  { id: "blocked", name: "Blocked", description: "Blocked Skill", status: "blocked", reason: "License missing" },
];

function createComponent() {
  const actions: SkillManagerAction[] = [];
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
  const component = new SkillManagerComponent(
    items,
    tui as never,
    theme as never,
    keybindings as never,
    (action) => actions.push(action),
  );
  return { component, actions, tui };
}

function createMcpComponent() {
  const actions: SkillManagerAction[] = [];
  const component = new SkillManagerComponent(
    [{
      id: "paper-search-mcp",
      name: "Paper Search MCP",
      description: "Search papers",
      status: "disabled",
      details: ["传输：stdio · 风险：network"],
    }],
    { requestRender: vi.fn() } as never,
    { bold: (text: string) => text, fg: (_color: string, text: string) => text } as never,
    {
      matches: (data: string, binding: string) => (
        (binding === "tui.select.confirm" && data === "ENTER") ||
        (binding === "tui.select.cancel" && data === "ESC")
      ),
    } as never,
    (action) => actions.push(action),
    {
      title: "MCP 管理",
      itemLabel: "MCP",
      enterAction: "install",
      disabledText: "项目配置已关闭",
    },
  );
  return { component, actions };
}

describe("SkillManagerComponent", () => {
  it("renders all stable states and details in one page", () => {
    const { component } = createComponent();
    const text = component.render(100).join("\n");
    expect(text).toContain("Skill 管理");
    expect(text).toContain("[◆] research-intake");
    expect(text).toContain("[●] Enabled");
    expect(text).toContain("[ ] Disabled");
    expect(text).toContain("[↓] Missing");
    expect(text).toContain("[!] Blocked");
  });

  it("keeps core Skills locked and explains why", () => {
    const { component, actions } = createComponent();
    component.handleInput(" ");
    expect(actions).toEqual([]);
    expect(component.render(100).join("\n")).toContain("核心 Skill 始终启用");
  });

  it("toggles installed Skills with Space", () => {
    const { component, actions } = createComponent();
    component.handleInput("DOWN");
    component.handleInput(" ");
    expect(actions).toEqual([{ type: "toggle", id: "enabled", enabled: false }]);
  });

  it("opens the install flow for missing Skills with Enter", () => {
    const { component, actions } = createComponent();
    component.handleInput("DOWN");
    component.handleInput("DOWN");
    component.handleInput("DOWN");
    component.handleInput("ENTER");
    expect(actions).toEqual([{ type: "install", id: "missing" }]);
  });

  it("shows blocked reasons without emitting an action", () => {
    const { component, actions } = createComponent();
    for (let index = 0; index < 4; index += 1) component.handleInput("DOWN");
    component.handleInput("ENTER");
    expect(actions).toEqual([]);
    expect(component.render(100).join("\n")).toContain("License missing");
  });

  it("closes with Escape", () => {
    const { component, actions } = createComponent();
    component.handleInput("ESC");
    expect(actions).toEqual([{ type: "close" }]);
  });

  it("emits enable-all with the a key", () => {
    const { component, actions } = createComponent();
    component.handleInput("a");
    expect(actions).toEqual([{ type: "toggle-all", enabled: true }]);
  });

  it("emits disable-all with the d key", () => {
    const { component, actions } = createComponent();
    component.handleInput("d");
    expect(actions).toEqual([{ type: "toggle-all", enabled: false }]);
  });

  it("supports an MCP management page with runtime-aware status and preflight", () => {
    const { component, actions } = createMcpComponent();
    const text = component.render(100).join("\n");
    expect(text).toContain("MCP 管理");
    expect(text).toContain("项目配置已关闭");
    expect(text).toContain("传输：stdio · 风险：network");
    component.handleInput("ENTER");
    expect(actions).toEqual([{ type: "install", id: "paper-search-mcp" }]);
  });

  it("allows a previously enabled MCP to be disabled after its preflight becomes blocked", () => {
    const actions: SkillManagerAction[] = [];
    const component = new SkillManagerComponent(
      [{
        id: "stale-mcp",
        name: "Stale MCP",
        description: "Previously configured",
        status: "blocked",
        configuredEnabled: true,
        reason: "Pinned source changed",
      }],
      { requestRender: vi.fn() } as never,
      { bold: (text: string) => text, fg: (_color: string, text: string) => text } as never,
      { matches: () => false } as never,
      (action) => actions.push(action),
      { itemLabel: "MCP" },
    );
    component.handleInput(" ");
    expect(actions).toEqual([{ type: "toggle", id: "stale-mcp", enabled: false }]);
  });
});
