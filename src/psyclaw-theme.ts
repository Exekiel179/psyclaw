/**
 * The psyclaw color theme for the bundled Pi TUI. It is a teal-dark variant of
 * Pi's built-in dark theme: the accent is a calm teal, headings/borders shift
 * cooler, and backgrounds get a faint teal tint. Every required color token is
 * present so the theme passes Pi's theme JSON schema.
 */
export const PSYCLAW_THEME_NAME = "psyclaw";

export const PSYCLAW_THEME = {
  name: PSYCLAW_THEME_NAME,
  vars: {
    cyan: "#2ec4b6",
    blue: "#4a90d9",
    green: "#7ec699",
    red: "#e06c75",
    yellow: "#e5c07b",
    text: "#d8dee9",
    gray: "#8b98a5",
    dimGray: "#5b6672",
    darkGray: "#3b4252",
    accent: "#2ec4b6",
    selectedBg: "#1f3a3d",
    userMsgBg: "#2a2f3a",
    toolPendingBg: "#2b303b",
    toolSuccessBg: "#1f3d34",
    toolErrorBg: "#3d2b2b",
    customMsgBg: "#27333b",
  },
  colors: {
    accent: "accent",
    border: "blue",
    borderAccent: "cyan",
    borderMuted: "darkGray",
    success: "green",
    error: "red",
    warning: "yellow",
    muted: "gray",
    dim: "dimGray",
    text: "text",
    thinkingText: "gray",

    selectedBg: "selectedBg",
    scrollbarThumb: "selectedBg",
    userMessageBg: "userMsgBg",
    userMessageText: "text",
    customMessageBg: "customMsgBg",
    customMessageText: "text",
    customMessageLabel: "#2ec4b6",
    toolPendingBg: "toolPendingBg",
    toolSuccessBg: "toolSuccessBg",
    toolErrorBg: "toolErrorBg",
    toolTitle: "text",
    toolOutput: "gray",

    mdHeading: "#e5c07b",
    mdLink: "#4fc3b8",
    mdLinkUrl: "dimGray",
    mdCode: "accent",
    mdCodeBlock: "green",
    mdCodeBlockBorder: "gray",
    mdQuote: "gray",
    mdQuoteBorder: "gray",
    mdHr: "gray",
    mdListBullet: "accent",

    toolDiffAdded: "green",
    toolDiffRemoved: "red",
    toolDiffContext: "gray",

    syntaxComment: "#7f9b7f",
    syntaxKeyword: "#61afef",
    syntaxFunction: "#98c379",
    syntaxVariable: "#d19a66",
    syntaxString: "#98c379",
    syntaxNumber: "#d19a66",
    syntaxType: "#2ec4b6",
    syntaxOperator: "#d8dee9",
    syntaxPunctuation: "#d8dee9",

    thinkingOff: "darkGray",
    thinkingMinimal: "#6e7b8a",
    thinkingLow: "#5f87af",
    thinkingMedium: "#6fb3b8",
    thinkingHigh: "#7ec4c8",
    thinkingXhigh: "#2ec4b6",
    thinkingMax: "#4dd0c9",

    bashMode: "green",
  },
  export: {
    pageBg: "#16181d",
    cardBg: "#1e222a",
    infoBg: "#202a2e",
  },
};
