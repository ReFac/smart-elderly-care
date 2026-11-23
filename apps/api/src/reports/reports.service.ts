import { Injectable, NotFoundException } from '@nestjs/common';
import { PrismaService } from '../prisma/prisma.service';

@Injectable()
export class ReportsService {
  constructor(private prisma: PrismaService) {}

  list(tenantId: string) {
    return this.prisma.reportSubmission.findMany({
      where: { tenantId },
      orderBy: { createdAt: 'desc' },
    });
  }

  create(tenantId: string, data: any) {
    return this.prisma.reportSubmission.create({
      data: {
        tenantId,
        reportType: data.reportType,
        period: data.period,
        status: 'draft',
        payloadJson: data.payloadJson,
      },
    });
  }

  async update(id: string, tenantId: string, data: any) {
    const row = await this.prisma.reportSubmission.findFirst({ where: { id, tenantId } });
    if (!row) throw new NotFoundException();
    return this.prisma.reportSubmission.update({
      where: { id },
      data: {
        status: data.status,
        payloadJson: data.payloadJson,
        fileUrl: data.fileUrl,
        submittedAt: data.status === 'submitted' ? new Date() : row.submittedAt,
      },
    });
  }

  async delete(id: string, tenantId: string) {
    const row = await this.prisma.reportSubmission.findFirst({ where: { id, tenantId } });
    if (!row) throw new NotFoundException();
    return this.prisma.reportSubmission.delete({ where: { id } });
  }

  /** Generate civil-affairs style monthly snapshot from live data. */
  async generateMonthly(tenantId: string, period?: string) {
    const p = period || new Date().toISOString().slice(0, 7);
    const [elders, beds, occupied, careGroups, unpaid] = await Promise.all([
      this.prisma.elder.count({ where: { tenantId, status: 'active' } }),
      this.prisma.bed.count({ where: { room: { floor: { building: { tenantId } } } } }),
      this.prisma.bed.count({
        where: { status: 'occupied', room: { floor: { building: { tenantId } } } },
      }),
      this.prisma.elder.groupBy({
        by: ['careLevel'],
        where: { tenantId, status: 'active' },
        _count: true,
      }),
      this.prisma.bill.count({
        where: { elder: { tenantId }, status: { in: ['unpaid', 'partial', 'overdue'] } },
      }),
    ]);
    const elderLedger = await this.prisma.elder.findMany({
      where: { tenantId, status: 'active' },
      select: {
        name: true,
        gender: true,
        careLevel: true,
        paymentType: true,
        checkInDate: true,
        bed: { select: { code: true } },
      },
    });
    const payload = {
      period: p,
      generatedAt: new Date().toISOString(),
      summary: {
        elders,
        beds,
        occupied,
        occupancyRate: beds ? Number(((occupied / beds) * 100).toFixed(1)) : 0,
        unpaidBills: unpaid,
        careLevelGroups: careGroups,
      },
      elderLedger,
    };
    return this.prisma.reportSubmission.create({
      data: {
        tenantId,
        reportType: 'civil_monthly',
        period: p,
        status: 'draft',
        payloadJson: JSON.stringify(payload),
      },
    });
  }

  async exportJson(id: string, tenantId: string) {
    const row = await this.prisma.reportSubmission.findFirst({ where: { id, tenantId } });
    if (!row) throw new NotFoundException();
    return {
      id: row.id,
      reportType: row.reportType,
      period: row.period,
      status: row.status,
      data: row.payloadJson ? JSON.parse(row.payloadJson) : null,
    };
  }
}
