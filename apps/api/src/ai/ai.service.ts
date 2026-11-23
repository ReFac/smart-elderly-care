import { Injectable } from '@nestjs/common';
import { SettingsService } from '../settings/settings.service';

@Injectable()
export class AiService {
  constructor(private settings: SettingsService) {}

  async ocr(tenantId: string, _fileMeta: { fileName?: string; mimeType?: string }) {
    const config = await this.settings.getAiConfigRaw(tenantId);
    const provider = config?.ocrProvider || 'mock';
    // Mock OCR for MVP; swap adapter by provider later (paddle/baidu/aliyun).
    return {
      provider,
      text: [
        '姓名：张三',
        '性别：男',
        '身份证号：110101194001011234',
        '过敏史：青霉素',
        '慢病：高血压',
        '自理等级：半失能',
      ].join('\n'),
      pages: 1,
    };
  }

  async extractForm(tenantId: string, text: string, formHint = 'elder_profile') {
    const config = await this.settings.getAiConfigRaw(tenantId);
    if (config?.apiKey && config.baseUrl) {
      try {
        const res = await fetch(`${config.baseUrl.replace(/\/$/, '')}/chat/completions`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            Authorization: `Bearer ${config.apiKey}`,
          },
          body: JSON.stringify({
            model: config.model || 'gpt-4o-mini',
            messages: [
              {
                role: 'system',
                content:
                  '你是养老院建档助手。从OCR文本提取JSON字段：name,gender,idNumber,allergies,chronicDiseases,careLevel。只返回JSON。',
              },
              { role: 'user', content: `表单类型:${formHint}\n文本:\n${text}` },
            ],
            temperature: 0.1,
          }),
        });
        if (res.ok) {
          const json: any = await res.json();
          const content = json.choices?.[0]?.message?.content || '{}';
          const match = content.match(/\{[\s\S]*\}/);
          return { source: 'llm', data: JSON.parse(match?.[0] || '{}') };
        }
      } catch {
        // fall through to heuristic
      }
    }
    return {
      source: 'heuristic',
      data: {
        name: text.match(/姓名[：:]\s*(\S+)/)?.[1] || '',
        gender: text.match(/性别[：:]\s*(\S+)/)?.[1] || '',
        idNumber: text.match(/身份证号[：:]\s*(\S+)/)?.[1] || '',
        allergies: text.match(/过敏史[：:]\s*(\S+)/)?.[1] || '',
        chronicDiseases: text.match(/慢病[：:]\s*(\S+)/)?.[1] || '',
        careLevel: text.includes('半失能')
          ? 'semi_disabled'
          : text.includes('失智')
            ? 'dementia'
            : text.includes('失能')
              ? 'disabled'
              : 'independent',
      },
    };
  }
}
