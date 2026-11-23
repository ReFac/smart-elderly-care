from __future__ import annotations

import json
from typing import Any

import httpx

from app.config import get_settings


class DeepSeekClient:
    """OpenAI 兼容协议，默认对接 DeepSeek；无 Key 时走本地启发式。"""

    def __init__(self) -> None:
        self.settings = get_settings()

    async def chat(self, system: str, user: str, temperature: float = 0.2) -> str:
        if not self.settings.llm_api_key:
            return self._heuristic(system, user)

        url = f"{self.settings.llm_base_url.rstrip('/')}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.settings.llm_api_key}",
            "Content-Type": "application/json",
        }
        body = {
            "model": self.settings.llm_model,
            "temperature": temperature,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(url, headers=headers, json=body)
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"]

    def _heuristic(self, system: str, user: str) -> str:
        text = user.lower()
        if "会议" in system or "纪要" in system:
            return json.dumps(
                {
                    "topics": ["交接班重点", "夜间巡视"],
                    "risks": ["失智走失风险"],
                    "todos": [{"title": "加强巡视", "owner": "值班护士", "due": "今晚24:00"}],
                    "conflicts": [],
                    "summary": "启发式纪要（未配置 LLM Key）。" + user[:120],
                },
                ensure_ascii=False,
            )
        if "照护" in system or "护理" in system:
            return json.dumps(
                {
                    "facts": {"actions": ["口述照护"], "anomaly": None},
                    "draft_text": user.strip(),
                },
                ensure_ascii=False,
            )
        if "意图" in system or "typeless" in system.lower():
            intent = "query_health"
            if any(k in text for k in ("告警", "摔倒", "sos")):
                intent = "raise_alert"
            elif any(k in text for k in ("记录", "翻身", "喂饭")):
                intent = "care_record"
            elif any(k in text for k in ("会议", "交接")):
                intent = "meeting"
            return json.dumps({"intent": intent, "slots": {}}, ensure_ascii=False)
        return user[:500]

    async def chat_json(self, system: str, user: str) -> dict[str, Any]:
        raw = await self.chat(system, user)
        try:
            start = raw.find("{")
            end = raw.rfind("}")
            if start >= 0 and end > start:
                return json.loads(raw[start : end + 1])
        except json.JSONDecodeError:
            pass
        return {"raw": raw}
