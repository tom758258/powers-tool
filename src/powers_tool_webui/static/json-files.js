export function buildNativeJsonPickerAccept() {
  return { "application/json": [".json"] };
}

export async function openJsonFile({ description, extensions }) {
  let text = "";
  let filename = "";
  const acceptMap = buildNativeJsonPickerAccept();
  if (window.showOpenFilePicker) {
    const [handle] = await window.showOpenFilePicker({
      types: [{ description, accept: acceptMap }],
      multiple: false
    });
    const file = await handle.getFile();
    text = await file.text();
    filename = file.name;
  } else {
    const fileInfo = await chooseJsonFile(buildJsonFileAccept(extensions));
    text = fileInfo.text;
    filename = fileInfo.name;
  }
  return { text, filename };
}

export function buildJsonFileAccept(extensions) {
  return [...extensions, "application/json"].join(",");
}

export function chooseJsonFile(accept) {
  return new Promise((resolve, reject) => {
    const input = document.createElement("input");
    let settled = false;
    let focusTimer = null;
    const cleanup = () => {
      window.clearTimeout(focusTimer);
      input.removeEventListener("change", onChange);
      input.removeEventListener("cancel", abort);
      window.removeEventListener("focus", onWindowFocus);
      input.remove();
    };
    const settle = (callback, value) => {
      if (settled) return;
      settled = true;
      cleanup();
      callback(value);
    };
    const abort = () => settle(reject, abortError("File selection cancelled."));
    const onWindowFocus = () => {
      window.clearTimeout(focusTimer);
      focusTimer = window.setTimeout(() => {
        if (!settled && (!input.files || input.files.length === 0)) abort();
      }, 0);
    };
    const onChange = async () => {
      try {
        if (!input.files?.[0]) return abort();
        const file = input.files[0];
        const text = await file.text();
        settle(resolve, { text, name: file.name });
      } catch (error) {
        settle(reject, error);
      }
    };
    input.type = "file";
    input.accept = accept;
    input.style.display = "none";
    input.addEventListener("change", onChange);
    input.addEventListener("cancel", abort);
    window.addEventListener("focus", onWindowFocus, { once: true });
    document.body.appendChild(input);
    input.click();
  });
}

export async function saveJsonFile(text, { description, extensions, suggestedName }) {
  const acceptMap = buildNativeJsonPickerAccept();
  if (window.showSaveFilePicker) {
    const handle = await window.showSaveFilePicker({ suggestedName, types: [{ description, accept: acceptMap }] });
    const writable = await handle.createWritable();
    await writable.write(text);
    await writable.close();
    return;
  }
  const url = URL.createObjectURL(new Blob([text], { type: "application/json" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = suggestedName;
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 0);
}

export function abortError(message) {
  if (typeof DOMException === "function") return new DOMException(message, "AbortError");
  const error = new Error(message);
  error.name = "AbortError";
  return error;
}

export function isAbortError(error) {
  return error?.name === "AbortError";
}
