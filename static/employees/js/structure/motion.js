// Short eased movements, skipped for anyone who asks their system for less motion.

const still = matchMedia("(prefers-reduced-motion: reduce)");

const easeOut = (t) => 1 - (1 - t) ** 3;

export const between = (from, to, t) => from + (to - from) * t;

export function tween(duration, step, done) {
  if (still.matches) {
    step(1);
    done?.();
    return { cancel() {} };
  }
  const start = performance.now();
  let frame = 0;
  const tick = (now) => {
    const t = Math.min(1, (now - start) / duration);
    step(easeOut(t));
    if (t < 1) frame = requestAnimationFrame(tick);
    else done?.();
  };
  frame = requestAnimationFrame(tick);
  return { cancel: () => cancelAnimationFrame(frame) };
}
