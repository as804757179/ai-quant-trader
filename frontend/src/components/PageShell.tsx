import { Typography } from "antd";
import type { ReactNode } from "react";

const { Title, Text } = Typography;

export interface PageShellProps {
  /** 页面主标题 */
  title: string;
  /** 副标题说明 */
  subtitle?: ReactNode;
  /** 右上角操作区 */
  extra?: ReactNode;
  children: ReactNode;
  className?: string;
}

/**
 * 全站统一页面容器：标题区 + 靠左全宽 + 紧凑内边距
 */
export default function PageShell({
  title,
  subtitle,
  extra,
  children,
  className,
}: PageShellProps) {
  return (
    <div className={`page-shell${className ? ` ${className}` : ""}`}>
      <header className="page-shell__header">
        <div>
          <Title level={4} className="page-shell__title">
            {title}
          </Title>
          {subtitle ? (
            typeof subtitle === "string" ? (
              <Text className="page-shell__subtitle">{subtitle}</Text>
            ) : (
              <div className="page-shell__subtitle">{subtitle}</div>
            )
          ) : null}
        </div>
        {extra ? <div className="page-shell__extra">{extra}</div> : null}
      </header>
      <div className="page-shell__body">{children}</div>
    </div>
  );
}
