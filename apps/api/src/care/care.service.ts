import { BadRequestException, Injectable, NotFoundException } from '@nestjs/common';
import { PrismaService } from '../prisma/prisma.service';
import { CARE_TASK_TEMPLATES } from '@nh/shared';

@Injectable()
export class CareService {
  constructor(private prisma: PrismaService) {}

  async generatePlan(elderId: string, tenantId: string) {
    const elder = await this.prisma.elder.findFirst({ where: { id: elderId, tenantId } });
    if (!elder) throw new NotFoundException('老人不存在');
    await this.prisma.carePlan.updateMany({
      where: { elderId, active: true },
      data: { active: false },
    });
    const items =
      CARE_TASK_TEMPLATES[elder.careLevel as keyof typeof CARE_TASK_TEMPLATES] ||
      CARE_TASK_TEMPLATES.independent;
    return this.prisma.carePlan.create({
      data: {
        elderId,
        careLevel: elder.careLevel,
        itemsJson: JSON.stringify(items),
        active: true,
      },
    });
  }

  listPlans(tenantId: string) {
    return this.prisma.carePlan.findMany({
      where: { active: true, elder: { tenantId } },
      include: { elder: { select: { id: true, name: true, careLevel: true } } },
      orderBy: { createdAt: 'desc' },
    });
  }

  async generateTodayTasks(tenantId: string) {
    const plans = await this.prisma.carePlan.findMany({
      where: { active: true, elder: { tenantId, status: 'active' } },
    });
    const dayStart = new Date();
    dayStart.setHours(0, 0, 0, 0);
    const dayEnd = new Date();
    dayEnd.setHours(23, 59, 59, 999);
    const created: any[] = [];
    for (const plan of plans) {
      const items: string[] = JSON.parse(plan.itemsJson || '[]');
      for (let i = 0; i < items.length; i++) {
        const scheduledAt = new Date(dayStart);
        scheduledAt.setHours(8 + i, 0, 0, 0);
        const exists = await this.prisma.careTask.findFirst({
          where: {
            elderId: plan.elderId,
            title: items[i],
            scheduledAt: { gte: dayStart, lte: dayEnd },
          },
        });
        if (exists) continue;
        const task = await this.prisma.careTask.create({
          data: {
            elderId: plan.elderId,
            carePlanId: plan.id,
            title: items[i],
            scheduledAt,
            status: 'pending',
          },
        });
        created.push(task);
      }
    }
    return { count: created.length, tasks: created };
  }

  listTasks(tenantId: string, date?: string, status?: string) {
    const day = date ? new Date(date) : new Date();
    const start = new Date(day);
    start.setHours(0, 0, 0, 0);
    const end = new Date(day);
    end.setHours(23, 59, 59, 999);
    return this.prisma.careTask.findMany({
      where: {
        elder: { tenantId },
        scheduledAt: { gte: start, lte: end },
        ...(status ? { status } : {}),
      },
      include: {
        elder: { select: { id: true, name: true, careLevel: true, wanderRisk: true } },
        checkins: { include: { caregiver: { select: { id: true, name: true } } } },
      },
      orderBy: { scheduledAt: 'asc' },
    });
  }

  async checkin(taskId: string, caregiverId: string, tenantId: string, data: any) {
    const task = await this.prisma.careTask.findFirst({
      where: { id: taskId, elder: { tenantId } },
    });
    if (!task) throw new NotFoundException('任务不存在');
    const checkin = await this.prisma.careCheckin.create({
      data: {
        careTaskId: taskId,
        caregiverId,
        photoUrl: data.photoUrl,
        note: data.note,
        anomaly: data.anomaly,
      },
    });
    await this.prisma.careTask.update({
      where: { id: taskId },
      data: { status: data.anomaly ? 'anomaly' : 'done' },
    });
    return checkin;
  }

  listOrders(tenantId: string) {
    return this.prisma.serviceOrder.findMany({
      where: { elder: { tenantId } },
      include: {
        elder: { select: { id: true, name: true } },
        createdBy: { select: { id: true, name: true } },
        assignee: { select: { id: true, name: true } },
      },
      orderBy: { createdAt: 'desc' },
    });
  }

  async createOrder(tenantId: string, createdById: string, data: any) {
    const elder = await this.prisma.elder.findFirst({ where: { id: data.elderId, tenantId } });
    if (!elder) throw new BadRequestException('老人不存在');
    return this.prisma.serviceOrder.create({
      data: {
        elderId: data.elderId,
        title: data.title,
        description: data.description,
        createdById,
        assigneeId: data.assigneeId,
        status: data.assigneeId ? 'assigned' : 'pending',
      },
    });
  }

  async updateOrder(id: string, tenantId: string, data: any) {
    const order = await this.prisma.serviceOrder.findFirst({
      where: { id, elder: { tenantId } },
    });
    if (!order) throw new NotFoundException('工单不存在');
    return this.prisma.serviceOrder.update({
      where: { id },
      data: {
        status: data.status,
        assigneeId: data.assigneeId,
        completedAt: data.status === 'done' ? new Date() : order.completedAt,
      },
    });
  }

  listVisits(tenantId: string) {
    return this.prisma.visitRecord.findMany({
      where: { elder: { tenantId } },
      include: { elder: { select: { id: true, name: true } } },
      orderBy: { visitAt: 'desc' },
      take: 100,
    });
  }

  async createVisit(tenantId: string, data: any) {
    const elder = await this.prisma.elder.findFirst({ where: { id: data.elderId, tenantId } });
    if (!elder) throw new BadRequestException('老人不存在');
    return this.prisma.visitRecord.create({
      data: {
        elderId: data.elderId,
        visitorName: data.visitorName,
        relation: data.relation,
        phone: data.phone,
        visitAt: data.visitAt ? new Date(data.visitAt) : new Date(),
        note: data.note,
      },
    });
  }
}
