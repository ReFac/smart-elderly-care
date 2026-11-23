# 智能养老 Agent Runtime（Python）

2026-11 Agent 工作台：Harness 护栏 + MCP 工具底座 + Hook/Skill 编排。

## 能力

1. 异构多源感知融合（CV / 60G 雷达 / 声学 AED / 呼叫终端）
2. 语音增量照护记录（ASR 文本 → 查重 → 草稿复核）
3. 会议纪要分层摘要与待办
4. Harness 权限边界与全链路审计
5. MCP 标准化工具调用
6. 告警反馈自迭代调阈
7. 床位独立上下文记忆
8. 分级推送路由
9. Typeless 全语音入口 + DeepSeek
10. 老人健康状态自动管理（草稿，禁终审）

## 启动

```bash
cd apps/agent
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # 填写 LLM_API_KEY / NEST_TOKEN（可选）
uvicorn app.main:app --host 0.0.0.0 --port 8100
```

健康检查：http://localhost:8100/health  
能力清单：http://localhost:8100/v1/manifest

## 与 Nest 对接

- 管理端 `/agent` 控制台通过 Vite 代理访问本服务
- MCP 工具 `elder.get_profile` 可携带 `NEST_TOKEN` 拉取档案
- 策略热更新：编辑 `policies/runtime.yaml`
