import { BadRequestException, Injectable, NotFoundException } from '@nestjs/common';
import { PrismaService } from '../prisma/prisma.service';
import { CARE_TASK_TEMPLATES } from '@nh/shared';

@Injectable()
export class EldersService {
  constructor(private prisma: PrismaService) {}

  list(tenantId: string, q?: string) {
    return this.prisma.elder.findMany({
      where: {
        tenantId,
        ...(q
          ? {
              OR: [
                { name: { contains: q } },
                { idNumber: { contains: q } },
                { phone: { contains: q } },
              ],
            }
          : {}),
      },
      include: {
        bed: { include: { room: { include: { floor: { include: { building: true } } } } } },
        health: true,
        contacts: true,
      },
      orderBy: { createdAt: 'desc' },
    });
  }

  async get(id: string, tenantId: string) {
    const elder = await this.prisma.elder.findFirst({
      where: { id, tenantId },
      include: {
        bed: { include: { room: { include: { floor: { include: { building: true } } } } } },
        health: true,
        contacts: true,
        contracts: { orderBy: { endDate: 'asc' } },
        bedChangeLogs: { orderBy: { createdAt: 'desc' }, take: 20 },
        mealRestrictions: true,
        emotionRecords: { orderBy: { recordedAt: 'desc' }, take: 20 },
      },
    });
    if (!elder) throw new NotFoundException('老人不存在');
    return elder;
  }

  async create(tenantId: string, data: any) {
    const { health, contacts, bedId, ...rest } = data;
    if (bedId) {
      const bed = await this.prisma.bed.findFirst({
        where: { id: bedId, room: { floor: { building: { tenantId } } } },
      });
      if (!bed) throw new BadRequestException('床位不存在');
      if (bed.status === 'occupied') throw new BadRequestException('床位已被占用');
    }
    return this.prisma.$transaction(async (tx) => {
      const elder = await tx.elder.create({
        data: {
          tenantId,
          name: rest.name,
          gender: rest.gender || 'unknown',
          idNumber: rest.idNumber,
          birthDate: rest.birthDate ? new Date(rest.birthDate) : null,
          phone: rest.phone,
          admitSource: rest.admitSource,
          paymentType: rest.paymentType || 'self',
          careLevel: rest.careLevel || 'independent',
          checkInDate: rest.checkInDate ? new Date(rest.checkInDate) : new Date(),
          depositAmount: rest.depositAmount || 0,
          wanderRisk: !!rest.wanderRisk,
          bedId: bedId || null,
          status: 'active',
          health: health
            ? {
                create: {
                  medicalHistory: health.medicalHistory,
                  allergies: health.allergies,
                  chronicDiseases: health.chronicDiseases,
                  forbiddenDrugs: health.forbiddenDrugs,
                  dietTaboos: health.dietTaboos,
                  assessmentNote: health.assessmentNote,
                },
              }
            : undefined,
          contacts: contacts?.length
            ? {
                create: contacts.map((c: any) => ({
                  name: c.name,
                  relation: c.relation,
                  phone: c.phone,
                  isEmergency: !!c.isEmergency,
                  isPrimary: !!c.isPrimary,
                })),
              }
            : undefined,
        },
        include: { health: true, contacts: true, bed: true },
      });
      if (bedId) {
        await tx.bed.update({ where: { id: bedId }, data: { status: 'occupied' } });
        await tx.bedChangeLog.create({
          data: { elderId: elder.id, toBedId: bedId, reason: '入住分床' },
        });
        if (rest.depositAmount > 0) {
          await tx.deposit.create({
            data: { elderId: elder.id, amount: rest.depositAmount, type: 'in', remark: '入住押金' },
          });
        }
      }
      const items = CARE_TASK_TEMPLATES[rest.careLevel as keyof typeof CARE_TASK_TEMPLATES] ||
        CARE_TASK_TEMPLATES.independent;
      await tx.carePlan.create({
        data: {
          elderId: elder.id,
          careLevel: elder.careLevel,
          itemsJson: JSON.stringify(items),
          active: true,
        },
      });
      return elder;
    });
  }

  async update(id: string, tenantId: string, data: any) {
    await this.get(id, tenantId);
    const { health, ...rest } = data;
    return this.prisma.$transaction(async (tx) => {
      const elder = await tx.elder.update({
        where: { id },
        data: {
          name: rest.name,
          gender: rest.gender,
          idNumber: rest.idNumber,
          birthDate: rest.birthDate ? new Date(rest.birthDate) : undefined,
          phone: rest.phone,
          admitSource: rest.admitSource,
          paymentType: rest.paymentType,
          careLevel: rest.careLevel,
          wanderRisk: rest.wanderRisk,
          depositAmount: rest.depositAmount,
          checkOutDate: rest.checkOutDate ? new Date(rest.checkOutDate) : undefined,
          status: rest.status,
        },
      });
      if (health) {
        await tx.elderHealth.upsert({
          where: { elderId: id },
          create: { elderId: id, ...health },
          update: health,
        });
      }
      return elder;
    });
  }

  async changeBed(id: string, tenantId: string, toBedId: string, reason?: string, operatedBy?: string) {
    const elder = await this.get(id, tenantId);
    const toBed = await this.prisma.bed.findFirst({
      where: { id: toBedId, room: { floor: { building: { tenantId } } } },
    });
    if (!toBed) throw new BadRequestException('目标床位不存在');
    if (toBed.status === 'occupied' && toBed.id !== elder.bedId) {
      throw new BadRequestException('目标床位已被占用');
    }
    return this.prisma.$transaction(async (tx) => {
      if (elder.bedId) {
        await tx.bed.update({ where: { id: elder.bedId }, data: { status: 'idle' } });
      }
      await tx.bed.update({ where: { id: toBedId }, data: { status: 'occupied' } });
      const updated = await tx.elder.update({ where: { id }, data: { bedId: toBedId } });
      await tx.bedChangeLog.create({
        data: {
          elderId: id,
          fromBedId: elder.bedId,
          toBedId,
          reason: reason || '调房换床',
          operatedBy,
        },
      });
      return updated;
    });
  }

  async addContract(elderId: string, tenantId: string, data: any) {
    await this.get(elderId, tenantId);
    return this.prisma.contract.create({
      data: {
        elderId,
        type: data.type,
        title: data.title,
        fileUrl: data.fileUrl,
        startDate: data.startDate ? new Date(data.startDate) : null,
        endDate: data.endDate ? new Date(data.endDate) : null,
      },
    });
  }

  async expiringContracts(tenantId: string, days = 30) {
    const until = new Date();
    until.setDate(until.getDate() + days);
    return this.prisma.contract.findMany({
      where: {
        elder: { tenantId },
        endDate: { lte: until, gte: new Date() },
      },
      include: { elder: { select: { id: true, name: true } } },
      orderBy: { endDate: 'asc' },
    });
  }

  async addEmotion(elderId: string, tenantId: string, data: any) {
    await this.get(elderId, tenantId);
    return this.prisma.emotionRecord.create({
      data: {
        elderId,
        mood: data.mood,
        behavior: data.behavior,
        note: data.note,
      },
    });
  }

  async addContact(elderId: string, tenantId: string, data: any) {
    await this.get(elderId, tenantId);
    return this.prisma.elderContact.create({
      data: {
        elderId,
        name: data.name,
        relation: data.relation,
        phone: data.phone,
        isEmergency: !!data.isEmergency,
        isPrimary: !!data.isPrimary,
      },
    });
  }
}
