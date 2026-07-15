import type { ReactNode } from "react";
import type { StatusTone } from "../presentation/contracts";

interface MetricCardProps {
  label: string;
  value: ReactNode;
  detail?: ReactNode;
  tone?: StatusTone;
  icon?: ReactNode;
}

export default function MetricCard({
  label,
  value,
  detail,
  tone = "idle",
  icon,
}: MetricCardProps) {
  return (
    <section className={`metric-card metric-card--${tone}`}>
      <div className="metric-card__heading">
        <span>{label}</span>
        {icon ? <span className="metric-card__icon">{icon}</span> : null}
      </div>
      <strong className="metric-card__value">{value}</strong>
      {detail ? <span className="metric-card__detail">{detail}</span> : null}
    </section>
  );
}
