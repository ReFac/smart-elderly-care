import { Injectable, NotFoundException } from '@nestjs/common';
import { PrismaService } from '../prisma/prisma.service';

@Injectable()
export class LtcService {
  constructor(private prisma: PrismaService) {}

  listAssessments(tenantId: string) {
    return this.prisma.ltcAssessment.findMany({
      where: { elder: { tenantId } },
      include: { elder: { select: { id: true, name: true, paymentType: true } } },
      orderBy: { assessDate: 'desc' },
    });
  }

  async createAssessment(tenantId: string, data: any) {
    const elder = await this.prisma.elder.findFirst({ where: { id: data.elderId, tenantId } });
    if (!elder) throw new NotFoundException('老人不存在');
    return this.prisma.ltcAssessment.create({
      data: {
        elderId: data.elderId,
        level: data.level,
        assessDate: new Date(data.assessDate || Date.now()),
        assessor: data.assessor,
        resultSummary: data.resultSummary,
        fileUrl: data.fileUrl,
        status: data.status || 'draft',
      },
    });
  }

  async updateAssessment(id: string, tenantId: string, data: any) {
    const row = await this.prisma.ltcAssessment.findFirst({ where: { id, elder: { tenantId } } });
    if (!row) throw new NotFoundException();
    return this.prisma.ltcAssessment.update({
      where: { id },
      data: {
        level: data.level,
        assessor: data.assessor,
        resultSummary: data.resultSummary,
        fileUrl: data.fileUrl,
        status: data.status,
      },
    });
  }

  listItems(tenantId: string) {
    return this.prisma.ltcServiceItem.findMany({ where: { tenantId, active: true } });
  }

  createItem(tenantId: string, data: any) {
    return this.prisma.ltcServiceItem.create({
      data: {
        tenantId,
        code: data.code,
        name: data.name,
        unitPrice: data.unitPrice || 0,
        unit: data.unit || '次',
      },
    });
  }

  listRecords(tenantId: string) {
    return this.prisma.ltcServiceRecord.findMany({
      where: { elder: { tenantId } },
      include: { elder: { select: { id: true, name: true } } },
      orderBy: { serviceAt: 'desc' },
      take: 200,
    });
  }

  async createRecord(tenantId: string, data: any) {
    const elder = await this.prisma.elder.findFirst({ where: { id: data.elderId, tenantId } });
    if (!elder) throw new NotFoundException('老人不存在');
    const item = data.itemCode
      ? await this.prisma.ltcServiceItem.findFirst({ where: { tenantId, code: data.itemCode } })
      : null;
    const quantity = data.quantity || 1;
    const unitPrice = item?.unitPrice ?? data.amount ?? 0;
    return this.prisma.ltcServiceRecord.create({
      data: {
        elderId: data.elderId,
        itemCode: data.itemCode || item?.code || 'custom',
        itemName: data.itemName || item?.name || '自定义服务',
        quantity,
        amount: data.amount ?? unitPrice * quantity,
        serviceAt: data.serviceAt ? new Date(data.serviceAt) : new Date(),
        caregiver: data.caregiver,
        evidenceUrl: data.evidenceUrl,
      },
    });
  }

  listReconciliations(tenantId: string) {
    return this.prisma.ltcReconciliation.findMany({
      where: { elder: { tenantId } },
      include: { elder: { select: { id: true, name: true } } },
      orderBy: { createdAt: 'desc' },
    });
  }

  async createReconciliation(tenantId: string, data: any) {
    const elder = await this.prisma.elder.findFirst({ where: { id: data.elderId, tenantId } });
    if (!elder) throw new NotFoundException('老人不存在');
    return this.prisma.ltcReconciliation.create({
      data: {
        elderId: data.elderId,
        period: data.period,
        claimAmount: data.claimAmount || 0,
        approvedAmount: data.approvedAmount || 0,
        status: data.status || 'pending',
        remark: data.remark,
      },
    });
  }

  async updateReconciliation(id: string, tenantId: string, data: any) {
    const row = await this.prisma.ltcReconciliation.findFirst({ where: { id, elder: { tenantId } } });
    if (!row) throw new NotFoundException();
    return this.prisma.ltcReconciliation.update({
      where: { id },
      data: {
        approvedAmount: data.approvedAmount,
        status: data.status,
        exportUrl: data.exportUrl,
        remark: data.remark,
      },
    });
  }

  /** Export payload for LTC claim package (skeleton). */
  async exportPackage(tenantId: string, elderId: string, period: string) {
    const elder = await this.prisma.elder.findFirst({
      where: { id: elderId, tenantId },
      include: { health: true },
    });
    if (!elder) throw new NotFoundException();
    const [assessments, records] = await Promise.all([
      this.prisma.ltcAssessment.findMany({ where: { elderId }, orderBy: { assessDate: 'desc' } }),
      this.prisma.ltcServiceRecord.findMany({ where: { elderId }, orderBy: { serviceAt: 'asc' } }),
    ]);
    return {
      meta: { period, exportedAt: new Date().toISOString(), format: 'ltc-claim-v1' },
      elder: {
        name: elder.name,
        idNumber: elder.idNumber,
        careLevel: elder.careLevel,
        paymentType: elder.paymentType,
      },
      assessments,
      serviceRecords: records,
      totals: {
        count: records.length,
        amount: records.reduce((s, r) => s + r.amount, 0),
      },
    };
  }
}
