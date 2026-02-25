# Campus Daily Agent (Canvas + Outlook + iPhone Push)

一个个人智能 agent 原型：
- 每天固定时间抓取 Outlook 学校邮箱并识别重要信息
- 从 Canvas 通知邮件中提取作业/截止时间（主来源）
- Canvas API 为可选增强（可不配置）
- 生成每日摘要并推送到 iPhone（Pushover）
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
1. 登录 Canvas -> `Account -> Settings`
2. 在 `Approved Integrations` 生成 Access Token
3. 填入:
- `CANVAS_BASE_URL` (例如 `https://xxx.instructure.com`)
- `CANVAS_TOKEN`

可选说明：
- 如果 `CANVAS_TOKEN` 留空，系统会自动跳过 Canvas API，不会报错。
- 此时任务主要来自 Outlook 里 Canvas 通知邮件解析。

### Outlook (Microsoft Graph)
1. 在 Azure Portal 注册应用
2. 给应用添加 Microsoft Graph Application 权限：
- `Mail.Read`
3. 管理员同意权限
4. 生成 client secret
5. 填入:
- `MS_TENANT_ID`
- `MS_CLIENT_ID`
- `MS_CLIENT_SECRET`
- `MS_USER_EMAIL`

### iPhone 推送 (Pushover)
1. iPhone 安装 Pushover App
2. 在 Pushover 网站创建 Application 获取 token
3. 填入:
- `PUSHOVER_APP_TOKEN`
- `PUSHOVER_USER_KEY`

## 3. 定时设置

- `SCHEDULE_TIME=07:30` 表示每天早上 07:30 推送
- `TIMEZONE=America/Los_Angeles`

## 4. Web 页面功能

- `刷新摘要`: 读取并展示当天数据
- `立即执行并推送`: 立即拉取 Outlook（和可选 Canvas）并发 iPhone 推送

## 5. 后续升级建议

- 推送升级为 Telegram Bot / Slack / 企业微信多通道
- 引入 LLM 总结邮件和任务优先级
- 增加 OAuth 登录和本地数据库
- 部署到云服务器（Railway/Fly.io/Render）实现 24x7 自动运行

## 6. 注意

- Outlook Application 权限读取邮箱涉及隐私和管理员许可，请只在个人受控环境使用。
- 本项目是 MVP，未包含完整鉴权、审计、重试和告警链路。
