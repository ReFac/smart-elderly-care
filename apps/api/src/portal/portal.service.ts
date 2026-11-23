import { Injectable } from '@nestjs/common';
import { PrismaService } from '../prisma/prisma.service';

/**
 * 用户端 / 员工端门户聚合（移动优先）。
 * 与管理端解耦，便于敏捷迭代独立发版。
 */
@Injectable()
export class PortalService {
  constructor(private prisma: PrismaService) {}

  async userHome(tenantId: string, userId: string) {
    const bindings = await this.prisma.familyBinding.findMany({
      where: { employeeId: userId },
      include: {
        elder: {
          select: { id: true, name: true, careLevel: true, status: true, bed: { select: { code: true } } },
        },
      },
    });
    const elderIds = bindings.map((b) => b.elderId);
    const [bills, meals, tours] = await Promise.all([
      elderIds.length
        ? this.prisma.bill.findMany({
            where: { elderId: { in: elderIds } },
            include: { lines: true },
            orderBy: { createdAt: 'desc' },
            take: 10,
          })
        : [],
      this.prisma.mealMenu.findMany({
        where: {
          tenantId,
          date: {
            gte: new Date(new Date().setHours(0, 0, 0, 0)),
            lte: new Date(new Date().setHours(23, 59, 59, 999)),
          },
        },
      }),
      this.prisma.roomTour.findMany({
        where: { tenantId, published: true },
        select: { id: true, title: true, coverUrl: true, sceneType: true },
        take: 6,
      }),
    ]);
    return {
      audience: 'user',
      elders: bindings.map((b) => ({ ...b.elder, relation: b.relation })),
      bills,
      mealsToday: meals,
      tours,
      stats: {
        openBills: bills.filter((b: any) => b.status !== 'paid').length,
        openCare: 0,
        tourCount: tours.length,
      },
      mobileHint: '优先适配手机 Chrome / Safari，微信公众号内可全屏浏览导览',
      capabilities: ['bills', 'meals', 'tours', 'visits'],
    };
  }

  async employeeHome(tenantId: string, userId: string) {
    const dayStart = new Date();
    dayStart.setHours(0, 0, 0, 0);
    const dayEnd = new Date();
    dayEnd.setHours(23, 59, 59, 999);
    const [tasks, orders, shifts, alerts] = await Promise.all([
      this.prisma.careTask.findMany({
        where: { elder: { tenantId }, scheduledAt: { gte: dayStart, lte: dayEnd } },
        include: { elder: { select: { id: true, name: true } } },
        orderBy: { scheduledAt: 'asc' },
        take: 50,
      }),
      this.prisma.serviceOrder.findMany({
        where: {
          elder: { tenantId },
          OR: [{ assigneeId: userId }, { status: { in: ['pending', 'assigned'] } }],
        },
        include: { elder: { select: { id: true, name: true } } },
        take: 30,
      }),
      this.prisma.shift.findMany({
        where: { tenantId, employeeId: userId, shiftDate: { gte: dayStart, lte: dayEnd } },
      }),
      this.prisma.alert.findMany({
        where: { tenantId, status: 'open' },
        orderBy: { createdAt: 'desc' },
        take: 10,
      }),
    ]);
    return {
      audience: 'employee',
      tasks,
      orders,
      shifts,
      alerts,
      stats: {
        openBills: 0,
        openCare: tasks.filter((t: any) => t.status !== 'done').length,
        openAlerts: alerts.length,
      },
      mobileHint: '员工移动端：今日任务与告警聚合',
      capabilities: ['care_checkin', 'orders', 'alerts', 'attendance'],
    };
  }
}
