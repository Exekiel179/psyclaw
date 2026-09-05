import { describe, expect, it } from "vitest";
import { ARS_REVIEW_SEATS } from "../../src/ars/contracts.js";
import { ARS_REVIEW_ROLES, arsReviewDispatchBatches } from "../../src/ars/panel-plan.js";
import { psyclawArsPatch } from "../../src/ars/profile.js";

describe("ARS review bridge plan", () => {
  it("uses the exact five-seat roster in a bounded 4+1 topology", () => {
    const batches = arsReviewDispatchBatches();
    expect(batches.map((batch) => batch.length)).toEqual([4, 1]);
    expect(batches.flat()).toEqual(ARS_REVIEW_SEATS);
    expect(ARS_REVIEW_SEATS.map((seat) => ARS_REVIEW_ROLES[seat])).toEqual(["eic", "methodology", "domain", "perspective", "da"]);
  });

  it("advertises process separation without claiming independent errors", () => {
    const patch = psyclawArsPatch();
    expect(patch).toContain("psyclaw_ars_multi_agent");
    expect(patch).toContain("do not establish independent error processes");
    expect(patch).toContain("three ordered fenced calls");
  });
});
