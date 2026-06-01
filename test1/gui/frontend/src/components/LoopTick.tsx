import { I } from "./Icon";

// A mutually-exclusive closed-loop scope tick. Shared by the Generator and
// Design Review tabs so the "run / fix errors / fix errors + warnings" run-mode
// controls look and behave identically in both.
export function LoopTick({
  label,
  title,
  checked,
  disabled,
  onToggle,
}: {
  label: string;
  title: string;
  checked: boolean;
  disabled?: boolean;
  onToggle: () => void;
}) {
  return (
    <label
      title={title}
      className={
        "inline-flex items-center gap-1.5 text-[12px] select-none cursor-pointer " +
        (disabled ? "opacity-50 pointer-events-none " : "") +
        (checked ? "text-ink-900" : "text-ink-600")
      }
    >
      <input
        type="checkbox"
        checked={checked}
        onChange={onToggle}
        disabled={disabled}
        className="accent-ink-900"
      />
      <I.Refresh size={12} className={checked ? "text-ink-900" : "text-ink-400"} />
      {label}
    </label>
  );
}
