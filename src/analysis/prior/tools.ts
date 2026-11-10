/**
 * Prior-mode tools. They no-op outside prior so analysis mode keeps its own plan path.
 */
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";
import type { PsyClawSessionMode } from "../../session/modes.js";
import { submitPriorRecall, submitPriorScript } from "./submit.js";

function toolText(text: string, isError = false): { content: [{ type: "text"; text: string }]; details: undefined; isError?: true } {
  return { content: [{ type: "text", text }], details: undefined, ...(isError ? { isError: true as const } : {}) };
}

export function registerPriorTools(pi: ExtensionAPI, getMode: () => PsyClawSessionMode): void {
  pi.registerTool({
    name: "psyclaw_submit_recall",
    label: "Submit prior recall",
    description: "Prior mode only. Before any data is read, submit one block per hypothesis with construct, internal validity, statistical conclusion, and dependence. Put each recalled approach on its own line as `- id: description`. Data tools stay closed until this is accepted.",
    parameters: Type.Object({
      recall: Type.String({ description: "Recall text. One hypothesis per section, with the four slots and `- id: description` lines for approaches." }),
    }),
    executionMode: "sequential",
    async execute(_toolCallId, params, _signal, _onUpdate, ctx) {
      if (getMode() !== "prior") return toolText("psyclaw_submit_recall is only used in prior mode. Press Shift+Tab until the footer shows prior.", true);
      const result = await submitPriorRecall(ctx.cwd, params.recall);
      return toolText(result.message, !result.accepted);
    },
  });

  pi.registerTool({
    name: "psyclaw_submit_plan_script",
    label: "Submit prior plan script",
    description: "Prior mode only, after recall. Submit the full analysis script. Labeled constants at the top are the plan. The script is checked and rendered to analysis/plans/plan.md. It is not run.",
    parameters: Type.Object({
      script: Type.String({ description: "Complete Python or R analysis script. Top-level constants use @intent, @declare, or @pseudo." }),
    }),
    executionMode: "sequential",
    async execute(_toolCallId, params, _signal, _onUpdate, ctx) {
      if (getMode() !== "prior") return toolText("psyclaw_submit_plan_script is only used in prior mode. Press Shift+Tab until the footer shows prior.", true);
      const result = await submitPriorScript(ctx.cwd, params.script);
      return toolText(result.message, !result.accepted);
    },
  });
}
