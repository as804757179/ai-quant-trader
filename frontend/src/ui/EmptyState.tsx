import { Empty } from "antd";

interface EmptyStateProps {
  description?: string;
}

export default function EmptyState({ description = "待接入" }: EmptyStateProps) {
  return (
    <div aria-live="polite" role="status">
      <Empty className="empty-state" image={Empty.PRESENTED_IMAGE_SIMPLE} description={description} />
    </div>
  );
}
