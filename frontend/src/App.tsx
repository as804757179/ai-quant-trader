import { ProLayout } from "@ant-design/pro-components";
import { Route, Routes, useNavigate } from "react-router-dom";
import Dashboard from "./pages/Dashboard";
import StockAnalysis from "./pages/StockAnalysis";
import Trade from "./pages/Trade";
import Placeholder from "./pages/Placeholder";

const menuRoutes = [
  { path: "/", name: "仪表盘" },
  { path: "/stock", name: "股票分析" },
  { path: "/ai", name: "AI决策" },
  { path: "/screener", name: "选股" },
  { path: "/strategy", name: "策略" },
  { path: "/backtest", name: "回测" },
  { path: "/risk", name: "风控" },
  { path: "/trade", name: "交易" },
];

export default function App() {
  const navigate = useNavigate();

  return (
    <ProLayout
      title="AI Quant Trader Pro"
      layout="mix"
      route={{ routes: menuRoutes }}
      menuItemRender={(item, dom) => (
        <span onClick={() => navigate(item.path || "/")}>{dom}</span>
      )}
    >
      <Routes>
        <Route path="/" element={<Dashboard />} />
        <Route path="/stock" element={<StockAnalysis />} />
        <Route path="/trade" element={<Trade />} />
        <Route path="/ai" element={<Placeholder title="AI决策中心" phase="Phase 2" />} />
        <Route path="/screener" element={<Placeholder title="选股系统" phase="Phase 3" />} />
        <Route path="/strategy" element={<Placeholder title="策略管理" phase="Phase 4" />} />
        <Route path="/backtest" element={<Placeholder title="回测系统" phase="Phase 4" />} />
        <Route path="/risk" element={<Placeholder title="风控中心" phase="Phase 3" />} />
      </Routes>
    </ProLayout>
  );
}