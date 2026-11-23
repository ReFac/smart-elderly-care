import { Injectable, NotFoundException } from '@nestjs/common';
import { PrismaService } from '../prisma/prisma.service';

@Injectable()
export class ToursService {
  constructor(private prisma: PrismaService) {}

  list(tenantId: string, publishedOnly = false) {
    return this.prisma.roomTour.findMany({
      where: { tenantId, ...(publishedOnly ? { published: true } : {}) },
      include: { hotspots: true },
      orderBy: { updatedAt: 'desc' },
    });
  }

  async get(id: string, tenantId?: string) {
    const tour = await this.prisma.roomTour.findFirst({
      where: { id, ...(tenantId ? { tenantId } : {}), },
      include: { hotspots: true },
    });
    if (!tour) throw new NotFoundException('导览不存在');
    return tour;
  }

  create(tenantId: string, data: any) {
    return this.prisma.roomTour.create({
      data: {
        tenantId,
        title: data.title,
        buildingId: data.buildingId,
        floorId: data.floorId,
        roomId: data.roomId,
        coverUrl: data.coverUrl,
        sceneType: data.sceneType || 'panorama',
        sceneUrl: data.sceneUrl,
        modelUrl: data.modelUrl,
        yaw: data.yaw ?? 0,
        pitch: data.pitch ?? 0,
        fov: data.fov ?? 75,
        published: !!data.published,
        metaJson: data.metaJson ? JSON.stringify(data.metaJson) : null,
        hotspots: data.hotspots?.length
          ? {
              create: data.hotspots.map((h: any) => ({
                label: h.label,
                kind: h.kind || 'info',
                yaw: h.yaw ?? 0,
                pitch: h.pitch ?? 0,
                targetTourId: h.targetTourId,
                payloadJson: h.payloadJson ? JSON.stringify(h.payloadJson) : null,
              })),
            }
          : undefined,
      },
      include: { hotspots: true },
    });
  }

  async update(id: string, tenantId: string, data: any) {
    const exists = await this.prisma.roomTour.findFirst({ where: { id, tenantId } });
    if (!exists) throw new NotFoundException();
    return this.prisma.roomTour.update({
      where: { id },
      data: {
        title: data.title,
        coverUrl: data.coverUrl,
        sceneType: data.sceneType,
        sceneUrl: data.sceneUrl,
        modelUrl: data.modelUrl,
        yaw: data.yaw,
        pitch: data.pitch,
        fov: data.fov,
        published: data.published,
        metaJson: data.metaJson != null ? JSON.stringify(data.metaJson) : undefined,
      },
      include: { hotspots: true },
    });
  }

  async addHotspot(tourId: string, tenantId: string, data: any) {
    await this.get(tourId, tenantId);
    return this.prisma.roomTourHotspot.create({
      data: {
        tourId,
        label: data.label,
        kind: data.kind || 'info',
        yaw: data.yaw ?? 0,
        pitch: data.pitch ?? 0,
        targetTourId: data.targetTourId,
        payloadJson: data.payloadJson ? JSON.stringify(data.payloadJson) : null,
      },
    });
  }

  async remove(id: string, tenantId: string) {
    await this.get(id, tenantId);
    return this.prisma.roomTour.delete({ where: { id } });
  }

  /** 公开列表：用户端 / 公众号 */
  publicList(tenantId?: string) {
    return this.prisma.roomTour.findMany({
      where: { published: true, ...(tenantId ? { tenantId } : {}) },
      include: { hotspots: true },
      orderBy: { updatedAt: 'desc' },
    });
  }
}
