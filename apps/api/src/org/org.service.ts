import { Injectable, NotFoundException } from '@nestjs/common';
import { PrismaService } from '../prisma/prisma.service';

@Injectable()
export class OrgService {
  constructor(private prisma: PrismaService) {}

  listBuildings(tenantId: string) {
    return this.prisma.building.findMany({
      where: { tenantId },
      include: {
        floors: {
          orderBy: { level: 'asc' },
          include: {
            rooms: {
              orderBy: { number: 'asc' },
              include: { beds: { orderBy: { code: 'asc' }, include: { elder: true } } },
            },
          },
        },
      },
      orderBy: { code: 'asc' },
    });
  }

  async floorView(floorId: string, tenantId: string) {
    const floor = await this.prisma.floor.findFirst({
      where: { id: floorId, building: { tenantId } },
      include: {
        building: true,
        rooms: {
          orderBy: { number: 'asc' },
          include: { beds: { orderBy: { code: 'asc' }, include: { elder: true } } },
        },
      },
    });
    if (!floor) throw new NotFoundException('楼层不存在');
    return floor;
  }

  async updateFloorPlan(floorId: string, tenantId: string, planImage: string) {
    const floor = await this.prisma.floor.findFirst({
      where: { id: floorId, building: { tenantId } },
    });
    if (!floor) throw new NotFoundException('楼层不存在');
    return this.prisma.floor.update({ where: { id: floorId }, data: { planImage } });
  }

  listBeds(tenantId: string, status?: string) {
    return this.prisma.bed.findMany({
      where: {
        ...(status ? { status } : {}),
        room: { floor: { building: { tenantId } } },
      },
      include: {
        elder: true,
        room: { include: { floor: { include: { building: true } } } },
      },
      orderBy: { code: 'asc' },
    });
  }

  async setBedStatus(bedId: string, tenantId: string, status: string) {
    const bed = await this.prisma.bed.findFirst({
      where: { id: bedId, room: { floor: { building: { tenantId } } } },
    });
    if (!bed) throw new NotFoundException('床位不存在');
    return this.prisma.bed.update({ where: { id: bedId }, data: { status } });
  }

  bedStats(tenantId: string) {
    return this.prisma.bed.groupBy({
      by: ['status'],
      where: { room: { floor: { building: { tenantId } } } },
      _count: true,
    });
  }
}
