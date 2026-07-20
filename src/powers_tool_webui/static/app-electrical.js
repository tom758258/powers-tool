(function registerElectricalHelpers(root) {
  "use strict";

  if (!Object.prototype.hasOwnProperty.call(root, "PowersToolWebUI")) {
    throw new Error("PowersToolWebUI.context must load before app-electrical.js.");
  }
  const namespace = root.PowersToolWebUI;
  if (namespace === null || typeof namespace !== "object") {
    throw new Error("PowersToolWebUI namespace must be a usable object.");
  }
  if (!Object.prototype.hasOwnProperty.call(namespace, "context")) {
    throw new Error("PowersToolWebUI.context must load before app-electrical.js.");
  }
  if (Object.prototype.hasOwnProperty.call(namespace, "electrical")) {
    throw new Error("PowersToolWebUI.electrical is already initialized.");
  }

  function resolveInputElectricalConstraint({
    parameterConstraints,
    electricalRatingsByModel,
    modelId,
    channel,
    parameterName
  }) {
    const constraint = parameterConstraints?.[parameterName];
    const parameter = !constraint ? null : {
      attributes: {
        ...(constraint.min !== undefined ? { min: String(constraint.min) } : {}),
        ...(constraint.max !== undefined ? { max: String(constraint.max) } : {}),
        step: String(constraint.step ?? "any"),
        ...(constraint.description ? { title: String(constraint.description) } : {})
      },
      ...(constraint.exclusive_min !== undefined ? { exclusiveMin: String(constraint.exclusive_min) } : {})
    };
    const ratings = electricalRatingsByModel?.[modelId]?.channels;
    const channels = !Array.isArray(ratings) ? [] : channel === "all"
      ? ratings
      : ratings.filter((rating) => String(rating.channel) === String(channel));
    const rating = channels.length ? {
      max_voltage: Math.min(...channels.map((item) => Number(item.max_voltage))),
      max_current: Math.min(...channels.map((item) => Number(item.max_current)))
    } : null;
    const electricalParameter = ["voltage", "start_voltage", "stop_voltage", "current"].includes(parameterName);
    const max = rating && electricalParameter
      ? String(parameterName === "current" ? rating.max_current : rating.max_voltage)
      : null;
    const override = max === null ? null : {
      attributes: {
        max,
        title: `Official independent-channel DC output rating: maximum ${max} ${parameterName === "current" ? "A" : "V"}.`
      }
    };
    return { parameter, rating, override };
  }

  try {
    Object.defineProperty(namespace, "electrical", {
      value: Object.freeze({ resolveInputElectricalConstraint }),
      enumerable: true,
      writable: false,
      configurable: false
    });
  } catch (error) {
    throw new Error("PowersToolWebUI namespace cannot define its electrical API.");
  }
})(globalThis);
