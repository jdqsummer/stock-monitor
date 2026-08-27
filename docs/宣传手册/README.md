# Stock Monitor 宣传落地页

单文件静态宣传页，零外部依赖，离线可打开。

## 本地预览

直接用浏览器打开 `landing.html` 即可（截图走相对路径 `screens/`）。

## 内容与脱敏

- 真实截图仅 1 张：`screens/five-stage-analysis.png`（DSH 五段分析详情，公共分析内容，已脱敏）
- 其余界面为 CSS 手绘示意，示例股票与数字均为演示值，不含任何真实用户数据
- 若需更新截图：登录生产，元素级截取五段分析内容区，替换同名 PNG 即可

## 部署到生产（可选）

作为独立路径 `/about` 提供，**持久 bind-mount**（不写进 `frontend_dist` 卷——前端容器重建时会 `cp` 覆盖该卷把文件冲掉）：

1. nginx.conf 已含 `/about` 路由（`location = /about` 301 + `location /about/` alias/index landing.html），随仓库提交
2. docker-compose.yml 已给 nginx 服务加 bind-mount `./docs/宣传手册:/usr/share/nginx/html/about`，随仓库提交
3. 服务器上确认 `docs/宣传手册/` 已含 `landing.html` 与 `screens/`（tarball 完整部署自带；存量服务器执行 `docker compose up -d nginx` 应用挂载）

> 注意：落地页不替换产品 SPA 首页 `/`，避免影响现有用户入口。
