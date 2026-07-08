import { Card } from "antd";

export default function Placeholder({ title, phase }: { title: string; phase: string }) {
  return (
    <div style={{ padding: 24 }}>
      <Card title={title}>{phase} 实现中，敬请期待。</Card>
    </div>
  );
}