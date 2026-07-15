# iamhc 自动签到脚本

自动登录 [api.hcnsec.cn](https://api.hcnsec.cn) 并执行每日签到，签到后通过 Telegram 推送通知（可选）。  
支持**多账户批量签到**。

---

## 配置 Secrets

在仓库 **Settings → Secrets and variables → Actions** 中添加以下 Secrets：

### 多账户模式（推荐）

| Secret 名称 | 说明 |
|-------------|------|
| `ACCOUNTS` | 每行一个账户，格式为 `email:password` |
| `TG_BOT_TOKEN` | Telegram Bot Token（可选） |
| `TG_CHAT_ID` | Telegram Chat ID（可选） |

**ACCOUNTS 示例值：**
```
alamsantoso12@gmail.com:password123
q0302336@gmail.com:mypassword456
user3@example.com:anotherpass
```

> 密码中含有冒号（`:`）也没问题，脚本只在第一个冒号处分割。

### 单账户模式（兼容旧配置）

如果不想用 `ACCOUNTS`，可以继续使用旧的两个 Secret：

| Secret 名称 | 说明 |
|-------------|------|
| `EMAIL` | 登录邮箱 |
| `PASSWORD` | 登录密码 |

---

## 手动触发

在仓库 **Actions** 页面选择 `iamhc Daily Checkin` 工作流，点击 **Run workflow** 即可手动触发。

---

## 获取 Telegram Bot Token 和 Chat ID

1. 在 Telegram 中搜索 `@BotFather`，发送 `/newbot` 创建机器人，获取 **Bot Token**
2. 搜索 `@userinfobot`，发送任意消息，获取你的 **Chat ID**
3. 先给你的 Bot 发一条消息（激活会话），否则 Bot 无法主动推送
