import { Injectable } from '@nestjs/common';
import { PrismaService } from '../prisma/prisma.service';

@Injectable()
export class MealsService {
  constructor(private prisma: PrismaService) {}

  list(tenantId: string, from?: string, to?: string) {
    const start = from ? new Date(from) : new Date();
    start.setHours(0, 0, 0, 0);
    const end = to ? new Date(to) : new Date(start);
    if (!to) end.setDate(end.getDate() + 7);
    end.setHours(23, 59, 59, 999);
    return this.prisma.mealMenu.findMany({
      where: { tenantId, date: { gte: start, lte: end } },
      orderBy: [{ date: 'asc' }, { mealType: 'asc' }],
    });
  }

  today(tenantId: string) {
    const start = new Date();
    start.setHours(0, 0, 0, 0);
    const end = new Date();
    end.setHours(23, 59, 59, 999);
    return this.prisma.mealMenu.findMany({
      where: { tenantId, date: { gte: start, lte: end } },
      orderBy: { mealType: 'asc' },
    });
  }

  upsert(tenantId: string, data: any) {
    const date = new Date(data.date);
    date.setHours(12, 0, 0, 0);
    return this.prisma.mealMenu.upsert({
      where: {
        tenantId_date_mealType: {
          tenantId,
          date,
          mealType: data.mealType,
        },
      },
      create: {
        tenantId,
        date,
        mealType: data.mealType,
        dishes: data.dishes,
        dietTags: data.dietTags,
      },
      update: {
        dishes: data.dishes,
        dietTags: data.dietTags,
      },
    });
  }
}
