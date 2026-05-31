// Small inline selector for "how many rounds should the loop run" — used by the
// Schematic Generator (Fix-errors / Fix-errors+warnings) and the Design Review
// (closed loop). Range 1–10, default 3 (marked Recommended). Kept tiny and
// label-led so it sits naturally next to the loop controls on either tab.
import { I } from "./Icon";

export const ROUNDS_MIN = 1;
export const ROUNDS_MAX = 10;
export const ROUNDS_DEFAULT = 3;

export function RoundsPicker({
  value,
  onChange,
  disabled,
  label = "rounds",
  title = "How many fix/review rounds to run before stopping. More rounds give the agent additional attempts to reach a clean result; 3 is recommended for most runs.",
}: {
  value: number;
  onChange: (n: number) => void;
  disabled?: boolean;
  label?: string;
  title?: string;
}) {
  return (
    <label
      title={title}
      className={
        "inline-flex items-center gap-1.5 text-[12px] select-none " +
        (disabled ? "opacity-50 pointer-events-none " : "") +
        "text-ink-600"
      }
    >
      <I.Refresh size={12} className="text-ink-400" />
      {label}
      <select
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        disabled={disabled}
        className="h-7 px-1.5 rounded-md border border-edge bg-white text-ink-900 text-[12px]"
      >
        {Array.from({ length: ROUNDS_MAX - ROUNDS_MIN + 1 }, (_, i) => ROUNDS_MIN + i).map((n) => (
          <option key={n} value={n}>
            {n}
            {n === ROUNDS_DEFAULT ? " (recommended)" : ""}
          </option>
        ))}
      </select>
    </label>
  );
}
