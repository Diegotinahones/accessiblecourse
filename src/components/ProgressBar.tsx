interface ProgressBarProps {
  label: string;
  value: number;
  valueText?: string;
}

export function ProgressBar({ label, value, valueText }: ProgressBarProps) {
  const safeValue = Math.round(Math.max(0, Math.min(100, value)));
  const accessibleValueText = valueText ?? `${safeValue}% completado`;

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between gap-4 text-sm font-medium text-subtle">
        <span aria-hidden="true">{label}</span>
        <span aria-hidden="true">{safeValue}%</span>
      </div>
      <progress
        aria-label={label}
        aria-valuetext={accessibleValueText}
        className="sr-only"
        key={`${label}-${safeValue}`}
        max={100}
        value={safeValue}
      />
      <div
        aria-hidden="true"
        className="h-3 overflow-hidden rounded-full bg-[var(--uoc-border)]"
      >
        <div
          className="h-full rounded-full bg-[var(--uoc-cyan)] transition-all duration-500"
          style={{ width: `${safeValue}%` }}
        />
      </div>
    </div>
  );
}
