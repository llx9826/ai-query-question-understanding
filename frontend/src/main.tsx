import React from 'react';
import ReactDOM from 'react-dom/client';
import { App as AntApp, ConfigProvider } from 'antd';
import zhCN from 'antd/locale/zh_CN';
import App from './App';
import 'antd/dist/reset.css';
import './styles.css';

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode><ConfigProvider locale={zhCN} theme={{ token: {
    colorPrimary: '#2563eb', borderRadius: 10, colorText: '#172b4d', colorTextSecondary: '#6b778c',
    fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif',
  }, components: { Button: { controlHeight: 38 }, Table: { headerBg: '#f7f9fc' } } }}>
    <AntApp><App /></AntApp>
  </ConfigProvider></React.StrictMode>,
);
