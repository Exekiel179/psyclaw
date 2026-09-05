import { ARS_REVIEW_SEATS, type ArsReviewSeat } from "./contracts.js";

export const ARS_REVIEW_ROLES: Readonly<Record<ArsReviewSeat, string>> = {
  EIC: "eic", R1: "methodology", R2: "domain", R3: "perspective", DA: "da",
};
export const ARS_REVIEW_AGENT_FILES: Readonly<Record<ArsReviewSeat, string>> = {
  EIC: "eic_agent.md", R1: "methodology_reviewer_agent.md", R2: "domain_reviewer_agent.md", R3: "perspective_reviewer_agent.md", DA: "devils_advocate_reviewer_agent.md",
};

export function arsReviewDispatchBatches(): ArsReviewSeat[][] {
  return [ARS_REVIEW_SEATS.slice(0, 4) as ArsReviewSeat[], [ARS_REVIEW_SEATS[4]]];
}
