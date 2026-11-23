import { Injectable } from '@nestjs/common';
import { PrismaService } from '../prisma/prisma.service';

@Injectable()
export class SettingsService {
  constructor(private prisma: PrismaService) {}

  flags(tenantId: string) {
    return this.prisma.featureFlag.findMany({ where: { tenantId } });
  }

  async setFlag(tenantId: string, key: string, enabled: boolean) {
    return this.prisma.featureFlag.upsert({
      where: { tenantId_key: { tenantId, key } },
      create: { tenantId, key, enabled },
      update: { enabled },
    });
  }

  async getAiConfig(tenantId: string) {
    const config = await this.prisma.systemAiConfig.findUnique({ where: { tenantId } });
    if (!config) return null;
    return { ...config, apiKey: config.apiKey ? '********' + config.apiKey.slice(-4) : '' };
  }

  async getAiConfigRaw(tenantId: string) {
    return this.prisma.systemAiConfig.findUnique({ where: { tenantId } });
  }

  upsertAiConfig(tenantId: string, data: any) {
    return this.prisma.systemAiConfig.upsert({
      where: { tenantId },
      create: {
        tenantId,
        provider: data.provider || 'openai_compatible',
        baseUrl: data.baseUrl || 'https://api.openai.com/v1',
        apiKey: data.apiKey || '',
        model: data.model || 'gpt-4o-mini',
        ocrProvider: data.ocrProvider || 'mock',
      },
      update: {
        provider: data.provider,
        baseUrl: data.baseUrl,
        apiKey: data.apiKey,
        model: data.model,
        ocrProvider: data.ocrProvider,
      },
    });
  }
}
