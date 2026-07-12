import { ProLayout } from "@ant-design/pro-components";
import { Route, Routes, useLocation, useNavigate } from "react-router-dom";
import Dashboard from "./pages/Dashboard";
import StockAnalysis from "./pages/StockAnalysis";
import Trade from "./pages/Trade";
import AI from "./pages/AI";
import Screener from "./pages/Screener";
import Strategy from "./pages/Strategy";
import Backtest from "./pages/Backtest";
import Risk from "./pages/Risk";
import Alerts from "./pages/Alerts";

const menuRoutes = [
  { path: "/", name: "仪表盘" },
  { path: "/stock", name: "股票分析" },
  { path: "/ai", name: "AI决策" },
  { path: "/screener", name: "智能选股" },
  { path: "/strategy", name: "策略管理" },
  { path: "/backtest", name: "策略回测" },
  { path: "/risk", name: "风险控制" },
  { path: "/alerts", name: "告警中心" },
  { path: "/trade", name: "模拟交易" },
];

export default function App() {
  const navigate = useNavigate();
  const location = useLocation();

  return (
    <ProLayout
      title="AI量化交易系统"
      layout="side"
      navTheme="light"
      fixSiderbar
      // 菜单固定展开，不随滚动/断点折叠
      breakpoint={false}
      collapsed={false}
      siderWidth={200}
      token={{
        sider: {
          colorMenuBackground: "#fff",
          colorBgMenuItemSelected: "rgba(22,119,255,0.1)",
          colorTextMenuSelected: "#1677ff",
          colorTextMenu: "rgba(0,0,0,0.88)",
        },
        pageContainer: {
          paddingBlockPageContainerContent: 0,
          paddingInlinePageContainerContent: 0,
        },
      }}
      contentStyle={{
        minHeight: "100vh",
        background: "#f5f6f8",
        margin: 0,
        padding: 0,
      }}
      route={{
        path: "/",
        routes: menuRoutes,
      }}
      location={{ pathname: location.pathname }}
      menuItemRender={(item) => (
        <div
          role="link"
          tabIndex={0}
          style={{
            cursor: "pointer",
            width: "100%",
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
          }}
          onClick={() => navigate(item.path || "/")}
          onKeyDown={(e) => {
            if (e.key === "Enter") navigate(item.path || "/");
          }}
        >
          {item.name}
        </div>
      )}
      // 隐藏折叠按钮区域，侧栏始终展开
      collapsedButtonRender={false}
      menuHeaderRender={(logo) => (
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 8,
            paddingInline: 8,
            cursor: "pointer",
          }}
          onClick={() => navigate("/")}
        >
          {logo}
          <span
            style={{
              fontWeight: 600,
              fontSize: 15,
              whiteSpace: "nowrap",
            }}
          >
            AI量化交易系统
          </span>
        </div>
      )}
    >
      <Routes>
        <Route path="/" element={<Dashboard />} />
        <Route path="/stock" element={<StockAnalysis />} />
        <Route path="/trade" element={<Trade />} />
        <Route path="/ai" element={<AI />} />
        <Route path="/screener" element={<Screener />} />
        <Route path="/strategy" element={<Strategy />} />
        <Route path="/backtest" element={<Backtest />} />
        <Route path="/risk" element={<Risk />} />
        <Route path="/alerts" element={<Alerts />} />
      </Routes>
    </ProLayout>
  );
}
