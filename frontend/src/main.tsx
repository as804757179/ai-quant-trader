import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { ConfigProvider, App as AntApp, theme } from "antd";
import zhCN from "antd/locale/zh_CN";
import App from "./App";
import "antd/dist/reset.css";
import "./styles/global.css";

const appTheme = {
  algorithm: theme.darkAlgorithm,
  token: {
    colorPrimary: "#1677ff",
    colorSuccess: "#2fb26a",
    colorError: "#eb4b59",
    colorWarning: "#e7a43b",
    colorBgBase: "#06111f",
    colorBgContainer: "#0b1a2d",
    colorBorder: "#18334f",
    borderRadius: 10,
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
      siderWidth: 232,
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
