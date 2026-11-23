import { Injectable, NotFoundException } from '@nestjs/common';
import { PrismaService } from '../prisma/prisma.service';

@Injectable()
export class SecurityService {
  constructor(private prisma: PrismaService) {}

  listAlerts(tenantId: string, status?: string) {
    return this.prisma.alert.findMany({
      where: { tenantId, ...(status ? { status } : {}) },
      orderBy: { createdAt: 'desc' },
      take: 200,
    });
  }

  createAlert(tenantId: string, data: any) {
    return this.prisma.alert.create({
      data: {
        tenantId,
        type: data.type || 'general',
        title: data.title,
        message: data.message,
        elderId: data.elderId,
        source: data.source || 'manual',
        severity: data.severity || 'medium',
        status: 'open',
      },
    });
  }

  async handleAlert(id: string, tenantId: string, handledBy: string, status = 'handled') {
    const row = await this.prisma.alert.findFirst({ where: { id, tenantId } });
    if (!row) throw new NotFoundException();
    return this.prisma.alert.update({
      where: { id },
      data: { status, handledBy, handledAt: new Date() },
    });
  }

  /** Risk scan from existing elder flags / anomalies. */
  async scanRisks(tenantId: string) {
    const wander = await this.prisma.elder.findMany({
      where: { tenantId, status: 'active', wanderRisk: true },
      select: { id: true, name: true },
    });
    const created: any[] = [];
    for (const e of wander) {
      const exists = await this.prisma.alert.findFirst({
        where: {
          tenantId,
          elderId: e.id,
          type: 'wander_risk',
          status: 'open',
        },
      });
      if (exists) continue;
      created.push(
        await this.prisma.alert.create({
          data: {
            tenantId,
            elderId: e.id,
            type: 'wander_risk',
            title: `走失风险：${e.name}`,
            message: '失智/走失风险标记为高，请加强巡视',
            source: 'risk_scan',
            severity: 'high',
          },
        }),
      );
    }
    const anomalies = await this.prisma.careCheckin.findMany({
      where: {
        anomaly: { not: null },
        careTask: { elder: { tenantId } },
        checkedAt: { gte: new Date(Date.now() - 24 * 3600 * 1000) },
      },
      include: { careTask: { include: { elder: true } } },
      take: 20,
    });
    for (const a of anomalies) {
      if (!a.anomaly) continue;
      created.push(
        await this.prisma.alert.create({
          data: {
            tenantId,
            elderId: a.careTask.elderId,
            type: 'care_anomaly',
            title: `照护异常：${a.careTask.elder.name}`,
            message: a.anomaly,
            source: 'care',
            severity: 'medium',
          },
        }),
      );
    }
    return { created: created.length, alerts: created };
  }

  listAccess(tenantId: string) {
    return this.prisma.accessLog.findMany({
      where: { tenantId },
      orderBy: { recordedAt: 'desc' },
      take: 200,
    });
  }

  createAccess(tenantId: string, data: any) {
    return this.prisma.accessLog.create({
      data: {
        tenantId,
        person: data.person,
        direction: data.direction || 'in',
        gate: data.gate,
        relatedElderId: data.relatedElderId,
        recordedAt: data.recordedAt ? new Date(data.recordedAt) : new Date(),
      },
    });
  }

  /** Hardware webhook stub for SOS / fall detectors. */
  async ingestHardware(tenantId: string, payload: any) {
    return this.createAlert(tenantId, {
      type: payload.type || 'sos',
      title: payload.title || '硬件告警',
      message: payload.message || JSON.stringify(payload),
      elderId: payload.elderId,
      source: 'hardware',
      severity: payload.severity || 'high',
    });
  }
}
