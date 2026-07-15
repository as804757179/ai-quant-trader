import { Tag } from "antd";
import type { StatusTone } from "../presentation/contracts";

interface StatusBadgeProps {
  label: string;
  tone?: StatusTone;
}

export default function StatusBadge({ label, tone = "idle" }: StatusBadgeProps) {
  return <Tag className={`status-badge status-badge--${tone}`}>{label}</Tag>;
}
