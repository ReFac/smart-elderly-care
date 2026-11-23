import { BadRequestException, Injectable, NotFoundException } from '@nestjs/common';
import { PrismaService } from '../prisma/prisma.service';

@Injectable()
export class MedicalService {
  constructor(private prisma: PrismaService) {}

  private async assertElder(elderId: string, tenantId: string) {
    const elder = await this.prisma.elder.findFirst({ where: { id: elderId, tenantId } });
    if (!elder) throw new NotFoundException('老人不存在');
    return elder;
  }

  // ---- vitals ----
  listVitals(tenantId: string, elderId?: string) {
    return this.prisma.vitalSign.findMany({
      where: { elder: { tenantId }, ...(elderId ? { elderId } : {}) },
      include: { elder: { select: { id: true, name: true } } },
      orderBy: { recordedAt: 'desc' },
      take: 200,
    });
  }

  async createVital(tenantId: string, data: any) {
    await this.assertElder(data.elderId, tenantId);
    return this.prisma.vitalSign.create({
      data: {
        elderId: data.elderId,
        recordedAt: data.recordedAt ? new Date(data.recordedAt) : new Date(),
        systolic: data.systolic,
        diastolic: data.diastolic,
        glucose: data.glucose,
        temperature: data.temperature,
        spo2: data.spo2,
        pulse: data.pulse,
        note: data.note,
      },
    });
  }

  async deleteVital(id: string, tenantId: string) {
    const row = await this.prisma.vitalSign.findFirst({ where: { id, elder: { tenantId } } });
    if (!row) throw new NotFoundException();
    return this.prisma.vitalSign.delete({ where: { id } });
  }

  // ---- drugs ----
  listDrugs(tenantId: string) {
    return this.prisma.drug.findMany({ where: { tenantId }, orderBy: { name: 'asc' } });
  }

  createDrug(tenantId: string, data: any) {
    return this.prisma.drug.create({
      data: {
        tenantId,
        name: data.name,
        spec: data.spec,
        unit: data.unit || '盒',
        quantity: data.quantity || 0,
        lowStock: data.lowStock ?? 5,
        expireAt: data.expireAt ? new Date(data.expireAt) : null,
        isHighRisk: !!data.isHighRisk,
      },
    });
  }

  async updateDrug(id: string, tenantId: string, data: any) {
    const drug = await this.prisma.drug.findFirst({ where: { id, tenantId } });
    if (!drug) throw new NotFoundException();
    return this.prisma.drug.update({
      where: { id },
      data: {
        name: data.name,
        spec: data.spec,
        unit: data.unit,
        lowStock: data.lowStock,
        expireAt: data.expireAt ? new Date(data.expireAt) : undefined,
        isHighRisk: data.isHighRisk,
      },
    });
  }

  async stockDrug(id: string, tenantId: string, type: string, quantity: number, remark?: string) {
    const drug = await this.prisma.drug.findFirst({ where: { id, tenantId } });
    if (!drug) throw new NotFoundException();
    const delta = type === 'out' ? -Math.abs(quantity) : Math.abs(quantity);
    const next = drug.quantity + delta;
    if (next < 0) throw new BadRequestException('库存不足');
    await this.prisma.drugStockLog.create({
      data: { drugId: id, type, quantity: Math.abs(quantity), remark },
    });
    return this.prisma.drug.update({ where: { id }, data: { quantity: next } });
  }

  // ---- medication plans / doses ----
  listPlans(tenantId: string) {
    return this.prisma.medicationPlan.findMany({
      where: { elder: { tenantId } },
      include: {
        elder: { select: { id: true, name: true } },
        drug: true,
        doses: { orderBy: { scheduledAt: 'desc' }, take: 5 },
      },
      orderBy: { id: 'desc' },
    });
  }

  async createPlan(tenantId: string, data: any) {
    await this.assertElder(data.elderId, tenantId);
    const drug = await this.prisma.drug.findFirst({ where: { id: data.drugId, tenantId } });
    if (!drug) throw new BadRequestException('药品不存在');
    const plan = await this.prisma.medicationPlan.create({
      data: {
        elderId: data.elderId,
        drugId: data.drugId,
        dosage: data.dosage,
        schedule: data.schedule || '每日一次',
        startDate: data.startDate ? new Date(data.startDate) : new Date(),
        endDate: data.endDate ? new Date(data.endDate) : null,
        note: data.note,
        active: true,
      },
    });
    const when = new Date();
    when.setHours(9, 0, 0, 0);
    await this.prisma.medicationDose.create({
      data: { planId: plan.id, scheduledAt: when, status: 'pending' },
    });
    return plan;
  }

  listDoses(tenantId: string, status?: string) {
    return this.prisma.medicationDose.findMany({
      where: {
        plan: { elder: { tenantId } },
        ...(status ? { status } : {}),
      },
      include: {
        plan: {
          include: {
            elder: { select: { id: true, name: true } },
            drug: true,
          },
        },
        nurse: { select: { id: true, name: true } },
      },
      orderBy: { scheduledAt: 'asc' },
      take: 200,
    });
  }

  async giveDose(id: string, tenantId: string, nurseId: string, data: any) {
    const dose = await this.prisma.medicationDose.findFirst({
      where: { id, plan: { elder: { tenantId } } },
    });
    if (!dose) throw new NotFoundException();
    return this.prisma.medicationDose.update({
      where: { id },
      data: {
        status: data.status || 'given',
        givenAt: data.status === 'missed' ? null : new Date(),
        missedReason: data.missedReason,
        note: data.note,
        nurseId,
      },
    });
  }

  // ---- adverse / exams / followups / orders / referrals ----
  listAdverse(tenantId: string) {
    return this.prisma.adverseReaction.findMany({
      where: { elder: { tenantId } },
      include: { elder: { select: { id: true, name: true } } },
      orderBy: { recordedAt: 'desc' },
    });
  }

  async createAdverse(tenantId: string, data: any) {
    await this.assertElder(data.elderId, tenantId);
    return this.prisma.adverseReaction.create({
      data: {
        elderId: data.elderId,
        drugName: data.drugName,
        reaction: data.reaction,
        severity: data.severity || 'mild',
        note: data.note,
      },
    });
  }

  listExams(tenantId: string) {
    return this.prisma.healthExam.findMany({
      where: { elder: { tenantId } },
      include: { elder: { select: { id: true, name: true } } },
      orderBy: { examDate: 'desc' },
    });
  }

  async createExam(tenantId: string, data: any) {
    await this.assertElder(data.elderId, tenantId);
    return this.prisma.healthExam.create({
      data: {
        elderId: data.elderId,
        examDate: new Date(data.examDate || Date.now()),
        examType: data.examType || 'regular',
        summary: data.summary,
        reportUrl: data.reportUrl,
        nextDueAt: data.nextDueAt ? new Date(data.nextDueAt) : null,
      },
    });
  }

  listFollowUps(tenantId: string) {
    return this.prisma.chronicFollowUp.findMany({
      where: { elder: { tenantId } },
      include: { elder: { select: { id: true, name: true } } },
      orderBy: { followDate: 'desc' },
    });
  }

  async createFollowUp(tenantId: string, data: any) {
    await this.assertElder(data.elderId, tenantId);
    return this.prisma.chronicFollowUp.create({
      data: {
        elderId: data.elderId,
        disease: data.disease,
        followDate: new Date(data.followDate || Date.now()),
        result: data.result,
        nextDate: data.nextDate ? new Date(data.nextDate) : null,
        note: data.note,
      },
    });
  }

  listOrders(tenantId: string) {
    return this.prisma.medicalOrder.findMany({
      where: { elder: { tenantId } },
      include: { elder: { select: { id: true, name: true } } },
      orderBy: { orderedAt: 'desc' },
    });
  }

  async createOrder(tenantId: string, data: any) {
    await this.assertElder(data.elderId, tenantId);
    return this.prisma.medicalOrder.create({
      data: {
        elderId: data.elderId,
        source: data.source || 'clinic',
        content: data.content,
        doctorName: data.doctorName,
        status: data.status || 'active',
      },
    });
  }

  async updateOrder(id: string, tenantId: string, data: any) {
    const row = await this.prisma.medicalOrder.findFirst({ where: { id, elder: { tenantId } } });
    if (!row) throw new NotFoundException();
    return this.prisma.medicalOrder.update({
      where: { id },
      data: { status: data.status, content: data.content, doctorName: data.doctorName },
    });
  }

  listReferrals(tenantId: string) {
    return this.prisma.referralRecord.findMany({
      where: { elder: { tenantId } },
      include: { elder: { select: { id: true, name: true } } },
      orderBy: { departAt: 'desc' },
    });
  }

  async createReferral(tenantId: string, data: any) {
    await this.assertElder(data.elderId, tenantId);
    return this.prisma.referralRecord.create({
      data: {
        elderId: data.elderId,
        hospital: data.hospital,
        reason: data.reason,
        departAt: data.departAt ? new Date(data.departAt) : new Date(),
        returnAt: data.returnAt ? new Date(data.returnAt) : null,
        escort: data.escort,
        ambulance120: !!data.ambulance120,
        handoverNote: data.handoverNote,
      },
    });
  }

  async updateReferral(id: string, tenantId: string, data: any) {
    const row = await this.prisma.referralRecord.findFirst({ where: { id, elder: { tenantId } } });
    if (!row) throw new NotFoundException();
    return this.prisma.referralRecord.update({
      where: { id },
      data: {
        returnAt: data.returnAt ? new Date(data.returnAt) : row.returnAt,
        handoverNote: data.handoverNote ?? row.handoverNote,
      },
    });
  }
}
