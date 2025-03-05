# 钉钉中越翻译机器人

这是一个基于钉钉自定义机器人的中越互译工具。当用户在钉钉群中@机器人并发送消息时，机器人会自动检测语言并进行翻译：
- 用户发送中文：机器人回复越南语翻译
- 用户发送越南语：机器人回复中文翻译

## 功能特点

- 自动识别中文和越南语
- 基于 DeepSeek 模型进行高质量翻译
- 支持两种运行模式：Webhook模式和Stream模式（推荐）
- 简单易用，只需@机器人即可使用

## 环境要求

- Python 3.8+
- 钉钉自定义机器人
- DeepSeek API 密钥

## 安装步骤

1. 克隆项目
```bash
git clone <仓库地址>
cd dingtalk-translator
```

2. 安装依赖
```bash
pip install -r requirements.txt
```

3. 配置机器人

在 `config.py` 中填入必要的配置信息：
- 钉钉应用的 APP_KEY 和 APP_SECRET
- DeepSeek API 密钥

或者，你可以通过环境变量设置这些配置：
```bash
export DINGTALK_APP_KEY="你的钉钉应用AppKey"
export DINGTALK_APP_SECRET="你的钉钉应用AppSecret"
export DEEPSEEK_API_KEY="你的DeepSeek API密钥"
```

## 运行方式

### 推荐：Stream模式（无需公网IP和内网穿透）

Stream模式是钉钉官方推荐的机器人运行方式，不需要公网地址和内网穿透，更加稳定可靠。

1. 在钉钉开发者平台启用Stream模式

   在[钉钉开发者后台](https://open-dev.dingtalk.com/) -> 应用开发 -> 你的应用 -> 消息推送，选择"Stream模式"并启用。

2. 启动Stream模式应用
   ```bash
   python stream_app.py
   ```

3. 添加机器人到钉钉群

   在群设置 -> 群机器人中添加自定义机器人

### 替代方案：Webhook模式（需要公网IP或内网穿透）

1. 启动Webhook服务
   ```bash
   python app.py
   ```

2. 在钉钉开发者后台设置机器人的回调地址为：
   ```
   http://你的服务器IP:5000/webhook
   ```
   
   若在本地开发，需使用内网穿透工具（如ngrok）获取公网地址

## 使用方法

在钉钉群中@机器人，并输入需要翻译的文本，机器人会自动回复翻译结果。

例如：
- 用户: "@翻译机器人 你好，这是一条测试消息"
- 机器人: "用户说: 你好，这是一条测试消息\n\n越南语翻译: Xin chào, đây là một tin nhắn thử nghiệm"

## 服务持久化运行

为确保服务长期稳定运行：

### Windows:
- 可使用NSSM将服务注册为Windows服务
- 或使用Windows计划任务定期检查并重启服务

### Linux:
- 使用systemd创建服务单元
- 或使用Supervisor进行进程管理

## 贡献指南

欢迎对项目提出建议或贡献代码。请先fork项目，创建功能分支，然后提交PR。

## 许可证

MIT 