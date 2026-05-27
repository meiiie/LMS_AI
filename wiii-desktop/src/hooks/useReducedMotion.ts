/**
 * useReducedMotion — respects prefers-reduced-motion media query.
 * Sprint 162b: Per-component motion control for Framer Motion animations.
 *
 * Usage:
 *   const reduced = useReducedMotion();
 *   <motion.div animate={reduced ? {} : { opacity: 1, x: 0 }} />
 *
 * Also exports a helper to conditionally return variants or empty:
 *   <motion.div variants={reduced ? undefined : slideDown} />
 */
import { useState, useEffect } from "react";

const QUERY = "(prefers-reduced-motion: reduce)";

export function useReducedMotion(): boolean {
  const [reduced, setReduced] = useState(() => {
    if (typeof window === "undefined") return false;
    if (typeof window.matchMedia !== "function") return false;
    return window.matchMedia(QUERY).matches;
  });

  useEffect(() => {
    if (
      typeof window === "undefined" ||
      typeof window.matchMedia !== "function"
    ) {
      return;
    }
    const mql = window.matchMedia(QUERY);
    const handler = (e: MediaQueryListEvent) => setReduced(e.matches);
    if (typeof mql.addEventListener === "function") {
      mql.addEventListener("change", handler);
      return () => mql.removeEventListener("change", handler);
    }
    mql.addListener(handler);
    return () => mql.removeListener(handler);
  }, []);

  return reduced;
}

/**
 * Returns animation variants only when motion is not reduced.
 * Shorthand: `variants={motionSafe(reduced, slideDown)}`
 */
export function motionSafe<T>(reduced: boolean, variants: T): T | undefined {
  return reduced ? undefined : variants;
}
