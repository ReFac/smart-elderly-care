import { Injectable, NotFoundException } from '@nestjs/common';
import * as bcrypt from 'bcryptjs';
import { PrismaService } from '../prisma/prisma.service';

@Injectable()
export class HrService {
  constructor(private prisma: PrismaService) {}

  listEmployees(tenantId: string) {
    return this.prisma.employee.findMany({
      where: { tenantId, role: { not: 'family' } },
      select: {
        id: true,
        username: true,
        name: true,
        phone: true,
        role: true,
        active: true,
        createdAt: true,
      },
      orderBy: { createdAt: 'asc' },
    });
  }

  async createEmployee(tenantId: string, data: any) {
    const passwordHash = await bcrypt.hash(data.password || '123456', 10);
    return this.prisma.employee.create({
      data: {
        tenantId,
        username: data.username,
        passwordHash,
        name: data.name,
        phone: data.phone,
        role: data.role || 'caregiver',
        active: true,
      },
      select: { id: true, username: true, name: true, phone: true, role: true, active: true },
    });
  }

  async updateEmployee(id: string, tenantId: string, data: any) {
    const emp = await this.prisma.employee.findFirst({ where: { id, tenantId } });
    if (!emp) throw new NotFoundException();
    return this.prisma.employee.update({
      where: { id },
      data: {
        name: data.name,
        phone: data.phone,
        role: data.role,
        active: data.active,
      },
      select: { id: true, username: true, name: true, phone: true, role: true, active: true },
    });
  }

  listShifts(tenantId: string, from?: string, to?: string) {
    const start = from ? new Date(from) : new Date();
    start.setHours(0, 0, 0, 0);
    const end = to ? new Date(to) : new Date(start);
    if (!to) end.setDate(end.getDate() + 7);
    end.setHours(23, 59, 59, 999);
    return this.prisma.shift.findMany({
      where: { tenantId, shiftDate: { gte: start, lte: end } },
      include: { employee: { select: { id: true, name: true, role: true } } },
      orderBy: [{ shiftDate: 'asc' }, { shiftType: 'asc' }],
    });
  }

  createShift(tenantId: string, data: any) {
    return this.prisma.shift.create({
      data: {
        tenantId,
        employeeId: data.employeeId,
        shiftDate: new Date(data.shiftDate),
        shiftType: data.shiftType || 'day',
        floorId: data.floorId,
        elderIds: data.elderIds,
      },
    });
  }

  async deleteShift(id: string, tenantId: string) {
    const row = await this.prisma.shift.findFirst({ where: { id, tenantId } });
    if (!row) throw new NotFoundException();
    return this.prisma.shift.delete({ where: { id } });
  }

  listAttendance(tenantId: string) {
    return this.prisma.attendance.findMany({
      where: { employee: { tenantId } },
      include: { employee: { select: { id: true, name: true, role: true } } },
      orderBy: { checkInAt: 'desc' },
      take: 200,
    });
  }

  async checkIn(employeeId: string, tenantId: string, note?: string) {
    const emp = await this.prisma.employee.findFirst({ where: { id: employeeId, tenantId } });
    if (!emp) throw new NotFoundException();
    return this.prisma.attendance.create({
      data: { employeeId, note, checkInAt: new Date() },
    });
  }

  async checkOut(id: string, tenantId: string) {
    const row = await this.prisma.attendance.findFirst({
      where: { id, employee: { tenantId } },
    });
    if (!row) throw new NotFoundException();
    return this.prisma.attendance.update({
      where: { id },
      data: { checkOutAt: new Date() },
    });
  }

  listPerformance(tenantId: string) {
    return this.prisma.performanceRecord.findMany({
      where: { employee: { tenantId } },
      include: { employee: { select: { id: true, name: true, role: true } } },
      orderBy: { createdAt: 'desc' },
    });
  }

  async computePerformance(tenantId: string, period: string) {
    const caregivers = await this.prisma.employee.findMany({
      where: { tenantId, role: { in: ['caregiver', 'nurse'] }, active: true },
    });
    const created: any[] = [];
    for (const emp of caregivers) {
      const checkins = await this.prisma.careCheckin.count({ where: { caregiverId: emp.id } });
      const ordersDone = await this.prisma.serviceOrder.count({
        where: { assigneeId: emp.id, status: 'done' },
      });
      const taskCount = checkins + ordersDone;
      const doneCount = taskCount;
      const score = Math.min(100, doneCount * 2);
      const bonusAmount = Math.round(score * 5);
      const rec = await this.prisma.performanceRecord.create({
        data: {
          employeeId: emp.id,
          period,
          taskCount,
          doneCount,
          score,
          bonusAmount,
          remark: '按打卡与工单完成量自动统计',
        },
      });
      created.push(rec);
    }
    return { count: created.length, records: created };
  }
}
