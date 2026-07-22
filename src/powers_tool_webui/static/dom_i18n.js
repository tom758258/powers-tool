import { t } from "./i18n.js";

const BINDINGS = Object.freeze([
  ["data-i18n", "textContent"],
  ["data-i18n-placeholder", "placeholder"],
  ["data-i18n-title", "title"],
  ["data-i18n-aria-label", "aria-label"],
]);

const SELECTOR = BINDINGS.map(([binding]) => `[${binding}]`).join(",");

export function applyStaticTranslations(root, translate = t) {
  if (!root || typeof root.querySelectorAll !== "function") {
    throw new TypeError("root must support querySelectorAll");
  }
  if (typeof translate !== "function") {
    throw new TypeError("translate must be a function");
  }

  let applied = 0;
  for (const element of root.querySelectorAll(SELECTOR)) {
    for (const [binding, target] of BINDINGS) {
      const key = element.getAttribute(binding);
      if (key === null) continue;
      const message = translate(key);
      if (target === "textContent") {
        element.textContent = message;
      } else {
        element.setAttribute(target, message);
      }
      applied += 1;
    }
  }
  return applied;
}
