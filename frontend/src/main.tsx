// antd v5 静态方法（message/notification/Modal.confirm）在 React 19 下需要此补丁
import '@ant-design/v5-patch-for-react-19';
import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App';
import { installConsoleInterceptor } from '@/utils/consoleInterceptor';
import './index.css';

// console.error/warn 上报到后端 system_logs（早于 React 渲染，避免漏掉启动期错误）
installConsoleInterceptor();

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
