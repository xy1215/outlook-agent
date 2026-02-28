# Campus Daily Agent (Canvas + Outlook + iPhone Push)

一个个人智能 agent 原型：
- 每天固定时间抓取 Outlook 学校邮箱并识别重要信息
- 使用 LLM 将邮件分为：立刻处理 / 本周待办 / 信息参考
- 待办任务仅来自 Canvas Calendar feed（`.ics`）
- 使用 LLM 对 Canvas 日历事件进行筛选，只保留需要完成的作业/任务
- 生成每日摘要并推送到 iPhone（Pushover）
- Outlook 使用 Delegated OAuth 登录，无需申请 Application Mail.Read 管理员审批
- 提供一个可交互图形页面查看详情和手动触发

## 1. 快速启动

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# 编辑 .env，至少填入 Microsoft Graph / Pushover 参数（Canvas 可选）
uvicorn app.main:app --reload --port 8000
```

打开: `http://127.0.0.1:8000`

## 2. 你需要准备的账号/API

### Canvas
1. 登录 Canvas -> `Calendar` -> `Calendar Feed`
2. 复制你的 `.ics` 订阅链接
3. 填入:
- `CANVAS_CALENDAR_FEED_URL`
- `CANVAS_FEED_CACHE_PATH`（默认 `data/canvas_feed_cache.json`）
- `CANVAS_FEED_REFRESH_HOURS`（默认 24）

可选说明：
- 系统每 24 小时刷新一次 feed 缓存；刷新失败时会回退到最近一次缓存结果，避免任务列表为空。
- 当前版本不再从邮件中提取待办任务。

### Outlook (Microsoft Graph, Delegated)
1. 在 Azure Portal 注册应用
2. 给应用添加 Microsoft Graph Delegated 权限：
- `Mail.Read`
- `offline_access`
- `User.Read`（可选）
3. 在 `Authentication` 中添加重定向 URI：
- `http://127.0.0.1:8000/auth/callback`
4. 生成 client secret
5. 填入:
- `MS_TENANT_ID`
- `MS_CLIENT_ID`
- `MS_CLIENT_SECRET`
- `MS_USER_EMAIL`
- `MS_REDIRECT_URI`
- `MS_TOKEN_STORE_PATH`
6. 启动后，在首页点击 `连接 Outlook` 完成首次授权

### iPhone 推送 (Pushover)
1. iPhone 安装 Pushover App
2. 在 Pushover 网站创建 Application 获取 token
3. 填入:
- `PUSHOVER_APP_TOKEN`
- `PUSHOVER_USER_KEY`

## 3. 定时设置

- `SCHEDULE_TIME=07:30` 表示每天早上 07:30 推送
- `TIMEZONE=America/Los_Angeles`
- `CANVAS_CALENDAR_FEED_URL` Canvas 日历 feed 链接（待办唯一来源）
- `CANVAS_FEED_REFRESH_HOURS=24` 每 24 小时更新 feed 缓存
- `TASK_REQUIRE_DUE=true` 左栏仅展示带截止日期的任务
- `PUSH_DUE_WITHIN_HOURS=48` 仅推送 48 小时内截止任务
- `PUSH_PERSONA=auto` 到期任务推送风格（`auto/senior/cute`）
- `LLM_API_KEY` + `LLM_MODEL` 用于 Canvas 日历事件分类（作业任务 vs 通知/announcement）
- `LLM_MAIL_ENABLED=false` 默认关闭邮件分诊 LLM（建议先关，省 token）
- `LLM_MAIL_MAX_CALLS_PER_RUN=8` 单次运行最多邮件 LLM 调用
- `LLM_CANVAS_MAX_CALLS_PER_RUN=24` 单次运行最多 Canvas 任务 LLM 调用
- `LLM_CACHE_TTL_HOURS=72` LLM 结果缓存时间，减少重复调用

## 4. Web 页面功能

- `连接 Outlook`: 首次授权 Microsoft 账号
- `断开 Outlook`: 删除本地 token，重新授权
- `刷新摘要`: 强制重新计算今日摘要（会更新 generated_at）
- `立即执行并推送`: 立即拉取 Outlook（和可选 Canvas）并发 iPhone 推送
- 页面将按「立刻处理 / 本周待办 / 信息参考」展示邮件分诊结果
- 页面单独展示即将到期催办文案（当前风格/学姐风/可爱风）
- 待办任务列表显示“剩余 X 小时 Y 分钟”（进度条保留，公式 `(当前时间-发布时间)/(截止时间-发布时间)`）
- 距离 DDL <= 6 小时时进度条强制红色 `#FF0000` 并显示呼吸灯

## 5. 后续升级建议

- 推送升级为 Telegram Bot / Slack / 企业微信多通道
- 引入 LLM 总结邮件和任务优先级
- 增加 OAuth 登录和本地数据库
- 部署到云服务器（Railway/Fly.io/Render）实现 24x7 自动运行

## 6. 注意

- 本地会保存 Microsoft refresh token 到 `data/ms_token.json`，请勿泄露该文件。
- 本项目是 MVP，未包含完整鉴权、审计、重试和告警链路。
