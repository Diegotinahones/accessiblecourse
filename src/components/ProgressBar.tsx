interface ProgressBarProps {
  label: string;
  value: number;
}

export function ProgressBar({ label, value }: ProgressBarProps) {
  const safeValue = Math.max(0, Math.min(100, value));

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between gap-4 text-sm font-medium text-subtle">
        <span>{label}</span>
        <span>{safeValue}%</span>
      </div>
      <div
        aria-label={label}
        aria-valuemax={100}
        aria-valuemin={0}
        aria-valuenow={safeValue}
        aria-valuetext={`${safeValue}% completado`}
        className="h-3 overflow-hidden rounded-full bg-[#dfe7df]"
        role="progressbar"
      >
        <div
          className="h-full rounded-full bg-[#0f766e] transition-all duration-500"
          style={{ width: `${safeValue}%` }}
        />
      </div>
    </div>
  );
}
