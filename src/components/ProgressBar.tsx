interface ProgressBarProps {
  label: string;
  value: number;
}

export function ProgressBar({ label, value }: ProgressBarProps) {
  const safeValue = Math.max(0, Math.min(100, value));

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between text-sm font-medium text-subtle">
        <span>{label}</span>
        <span>{safeValue}%</span>
      </div>
      <div aria-hidden="true" className="h-3 rounded-full bg-slate-200">
        <div
          className="h-3 rounded-full bg-ink transition-[width] duration-500"
          style={{ width: `${safeValue}%` }}
        />
      </div>
    </div>
  );
}
