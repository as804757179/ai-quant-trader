import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { ConfigProvider, App as AntApp, theme } from "antd";
import zhCN from "antd/locale/zh_CN";
import dayjs from "dayjs";
import "dayjs/locale/zh-cn";
import utc from "dayjs/plugin/utc";
import timezone from "dayjs/plugin/timezone";
import App from "./App";
import "antd/dist/reset.css";
import "./styles/global.css";

dayjs.extend(utc);
dayjs.extend(timezone);
dayjs.locale("zh-cn");
dayjs.tz.setDefault("Asia/Shanghai");

const appTheme = {
  algorithm: theme.defaultAlgorithm,
  token: {
    colorPrimary: "#1677ff",
    colorSuccess: "#389e0d",
    colorError: "#cf1322",
    colorWarning: "#d48806",
    borderRadius: 8,
    fontFamily:
      '"Microsoft YaHei", "PingFang SC", "Noto Sans SC", "Segoe UI", system-ui, sans-serif',
    fontSize: 14,
    controlHeight: 36,
  },
  components: {
    Card: {
      headerFontSize: 15,
      headerHeight: 48,
    },
    Table: {
      cellPaddingBlock: 10,
      cellPaddingInline: 12,
    },
    Layout: {
      headerHeight: 56,
      siderWidth: 208,
    },
  },
};

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <ConfigProvider locale={zhCN} theme={appTheme}>
      <AntApp>
        <BrowserRouter>
          <App />
        </BrowserRouter>
      </AntApp>
    </ConfigProvider>
  </React.StrictMode>
);
