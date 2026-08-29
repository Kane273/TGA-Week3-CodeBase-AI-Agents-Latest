window.ResearchGuardMessages = {
  en: {
    ready: "Ready", starting: "Starting", planning: "Planning research", researching: "Collecting evidence",
    recovering: "Recovering evidence", designing: "Designing study", reviewing: "Reviewing protocol",
    approval: "Awaiting human approval", complete: "Protocol complete", queued: "Queued",
    running: "Agents working", failed: "Run failed", cancelled: "Run cancelled", cancelling: "Cancelling",
    waiting: "Waiting", inProgress: "In progress", completed: "Complete", noResults: "No matching results",
    archive: "Archive", restore: "Restore", delete: "Delete", resume: "Resume", copied: "Resume link copied",
    scorecard: "Run scorecard", presentation: "Presentation mode", traceability: "Evidence traceability",
    disagreement: "Agent disagreement", commandPalette: "Command palette", highContrast: "High contrast"
  }
};
window.rgLocale = localStorage.getItem("rg-locale") || "en";
window.rgT = (key) => window.ResearchGuardMessages[window.rgLocale]?.[key] || key;
