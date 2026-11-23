import { Injectable } from '@nestjs/common';
import { PrismaService } from '../prisma/prisma.service';

@Injectable()
export class GpsService {
  constructor(private prisma: PrismaService) {}

  async ingest(payload: {
    elderId: string;
    deviceId: string;
    lat: number;
    lng: number;
    recordedAt?: string;
  }) {
    const loc = await this.prisma.deviceLocation.create({
      data: {
        elderId: payload.elderId,
        deviceId: payload.deviceId,
        lat: payload.lat,
        lng: payload.lng,
        recordedAt: payload.recordedAt ? new Date(payload.recordedAt) : new Date(),
      },
    });
    // Geofence evaluation reserved for later.
    return { location: loc, alert: null, note: 'GPS 围栏告警服务已预留' };
  }

  latest(elderId: string) {
    return this.prisma.deviceLocation.findFirst({
      where: { elderId },
      orderBy: { recordedAt: 'desc' },
    });
  }
}
