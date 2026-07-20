(function registerContextHelpers(root) {
  "use strict";

  const namespace = root.PowersToolWebUI || {};
  if (namespace.context) {
    throw new Error("PowersToolWebUI.context is already initialized.");
  }

  function isNoHardwareExecutionMode(mode) {
    return mode === "simulate" || mode === "dry-run";
  }

  function buildWorkspaceResultKey(context) {
    return JSON.stringify({
      command: context.command || "",
      executionMode: context.executionMode || "real",
      resource: context.resource || "",
      expectedModelGuard: context.expectedModelGuard || "",
      canonicalModelId: context.canonicalModelId || "",
      planningModelId: context.planningModelId || "",
      planningProfileId: context.planningProfileId || ""
    });
  }

  function buildWorkspaceResultContextForJob(job, modelMaps = {}) {
    const runtime = job?.runtime || {};
    const executionMode = runtime.simulate === true ? "simulate" : runtime.dry_run === true ? "dry-run" : "real";
    if (executionMode === "simulate") {
      return { command: job.command, executionMode, planningModelId: runtime.planning_model_id || "" };
    }
    if (executionMode === "dry-run") {
      return {
        command: job.command,
        executionMode,
        planningModelId: runtime.planning_model_id || "",
        planningProfileId: runtime.planning_profile_id || ""
      };
    }
    const resultResource = job?.result?.resource;
    const resource = runtime.resource || resultResource?.name || (typeof resultResource === "string" ? resultResource : "");
    const canonicalModelId = [
      resultResource?.model_id,
      job?.result?.live_support?.model_id,
      job?.result?.resolved_identity?.model_id,
      job?.result?.model_id,
      modelMaps.commandModelByResource?.[resource],
      modelMaps.channelModelByResource?.[resource]
    ].find((value) => typeof value === "string" && value.trim()) || "";
    return {
      command: job.command,
      executionMode,
      resource,
      expectedModelGuard: runtime.expected_model_id || "",
      canonicalModelId
    };
  }

  function buildCurrentWorkspaceResultContext(snapshot) {
    const {
      command,
      executionMode,
      planningIdentity = "",
      resource = "",
      expectedModelGuard = "",
      canonicalModelId = ""
    } = snapshot;
    if (executionMode === "simulate") {
      return { command, executionMode, planningModelId: planningIdentity || "" };
    }
    if (executionMode === "dry-run") {
      return planningIdentity.startsWith("profile:")
        ? { command, executionMode, planningProfileId: planningIdentity.slice("profile:".length) }
        : { command, executionMode, planningModelId: planningIdentity };
    }
    return {
      command,
      executionMode: "real",
      resource,
      expectedModelGuard,
      canonicalModelId
    };
  }

  Object.defineProperty(namespace, "context", {
    value: Object.freeze({
      isNoHardwareExecutionMode,
      buildWorkspaceResultKey,
      buildWorkspaceResultContextForJob,
      buildCurrentWorkspaceResultContext
    }),
    enumerable: true,
    writable: false,
    configurable: false
  });
  if (!root.PowersToolWebUI) {
    Object.defineProperty(root, "PowersToolWebUI", {
      value: namespace,
      enumerable: true,
      writable: false,
      configurable: false
    });
  }
})(globalThis);
