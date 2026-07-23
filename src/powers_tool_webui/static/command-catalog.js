import { sourceT, t } from "./i18n.js";

export const COMMAND_CATEGORIES = ["output", "workflow", "protection", "trigger", "artifact", "discovery"];

export const COMMAND_CATEGORY_LABELS = {
  output: "Output",
  workflow: "Output Workflows",
  protection: "Protection",
  trigger: "Trigger",
  artifact: "Snapshot",
  discovery: "Advanced Diagnostics"
};

export function commandCategoryLabel(category) {
  return t(`command.category.${category}`, undefined, COMMAND_CATEGORY_LABELS[category] || category);
}

export function commandMessageKey(kind, command) {
  return `command.${kind}.${String(command).replaceAll("-", "_").replaceAll(" ", "_")}`;
}

export function commandDisplayName(command, rawFallback) {
  return t(commandMessageKey("name", command), undefined, rawFallback);
}

export function commandSourceDisplayName(command, rawFallback) {
  return sourceT(commandMessageKey("name", command), undefined, rawFallback);
}

export function commandDescription(command, rawFallback) {
  return t(commandMessageKey("description", command), undefined, rawFallback);
}
