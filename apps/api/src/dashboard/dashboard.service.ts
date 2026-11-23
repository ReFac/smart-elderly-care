import { Injectable } from '@nestjs/common';
import { PrismaService } from '../prisma/prisma.service';

@Injectable()
export class DashboardService {
  constructor(private prisma: PrismaService) {}

  async overview(tenantId: string) {
    const [totalBeds, occupiedBeds, activeElders, unpaidBills, pendingTasks, expiringContracts] =
      await Promise.all([
        this.prisma.bed.count({ where: { room: { floor: { building: { tenantId } } } } }),
        this.prisma.bed.count({
          where: { status: 'occupied', room: { floor: { building: { tenantId } } } },
        }),
        this.prisma.elder.count({ where: { tenantId, status: 'active' } }),
        this.prisma.bill.count({
          where: {
            elder: { tenantId },
            status: { in: ['unpaid', 'partial', 'overdue'] },
          },
        }),
        this.prisma.careTask.count({
          where: {
            status: 'pending',
            elder: { tenantId },
            scheduledAt: {
              gte: new Date(new Date().setHours(0, 0, 0, 0)),
              lte: new Date(new Date().setHours(23, 59, 59, 999)),
            },
          },
        }),
        this.prisma.contract.count({
          where: {
            elder: { tenantId },
            endDate: {
              gte: new Date(),
              lte: new Date(Date.now() + 30 * 24 * 3600 * 1000),
            },
          },
        }),
      ]);

    const careLevelGroups = await this.prisma.elder.groupBy({
      by: ['careLevel'],
      where: { tenantId, status: 'active' },
      _count: true,
    });

    const monthStart = new Date();
    monthStart.setDate(1);
    monthStart.setHours(0, 0, 0, 0);
    const revenue = await this.prisma.payment.aggregate({
      where: {
        paidAt: { gte: monthStart },
        bill: { elder: { tenantId } },
      },
      _sum: { amount: true },
    });

    return {
      totalBeds,
      occupiedBeds,
      idleBeds: totalBeds - occupiedBeds,
      occupancyRate: totalBeds ? Number(((occupiedBeds / totalBeds) * 100).toFixed(1)) : 0,
      activeElders,
      unpaidBills,
      pendingTasks,
      expiringContracts,
      careLevelGroups,
      monthRevenue: revenue._sum.amount || 0,
    };
  }
}
