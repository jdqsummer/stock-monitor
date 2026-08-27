# Stock Monitor 宣传落地页

单文件静态宣传页，零外部依赖，离线可打开。

## 本地预览

直接用浏览器打开 `landing.html` 即可（截图走相对路径 `screens/`）。

## 内容与脱敏

- 真实截图仅 1 张：`screens/five-stage-analysis.png`（DSH 五段分析详情，公共分析内容，已脱敏）
- 其余界面为 CSS 手绘示意，示例股票与数字均为演示值，不含任何真实用户数据
- 若需更新截图：登录生产，元素级截取五段分析内容区，替换同名 PNG 即可

## 部署到生产（可选）

将 `landing.html` 与 `screens/` 放入 nginx 静态目录，作为独立路径 `/about` 提供：

1. 服务器 `frontend_dist` 卷中新建 `about/` 目录，拷入 `landing.html` 与 `screens/` 目录（即 `about/landing.html` + `about/screens/five-stage-analysis.png`）
2. nginx location 添加：
   ```nginx
   location = /about { return 301 /about/; }
   location /about/ {
       alias /usr/share/nginx/html/about/;
       index landing.html;
   }
   ```
3. `docker compose exec nginx nginx -s reload`

> 注意：落地页不替换产品 SPA 首页 `/`，避免影响现有用户入口。
