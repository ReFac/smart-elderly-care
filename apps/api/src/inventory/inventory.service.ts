import { BadRequestException, Injectable, NotFoundException } from '@nestjs/common';
import { PrismaService } from '../prisma/prisma.service';

@Injectable()
export class InventoryService {
  constructor(private prisma: PrismaService) {}

  listItems(tenantId: string) {
    return this.prisma.inventoryItem.findMany({
      where: { tenantId },
      include: { stockLogs: { orderBy: { createdAt: 'desc' }, take: 5 } },
      orderBy: { name: 'asc' },
    });
  }

  createItem(tenantId: string, data: any) {
    return this.prisma.inventoryItem.create({
      data: {
        tenantId,
        name: data.name,
        sku: data.sku,
        category: data.category || 'consumable',
        quantity: data.quantity || 0,
        unit: data.unit || '件',
        lowStock: data.lowStock ?? 10,
        expireAt: data.expireAt ? new Date(data.expireAt) : null,
      },
    });
  }

  async updateItem(id: string, tenantId: string, data: any) {
    const item = await this.prisma.inventoryItem.findFirst({ where: { id, tenantId } });
    if (!item) throw new NotFoundException();
    return this.prisma.inventoryItem.update({
      where: { id },
      data: {
        name: data.name,
        sku: data.sku,
        category: data.category,
        unit: data.unit,
        lowStock: data.lowStock,
        expireAt: data.expireAt ? new Date(data.expireAt) : undefined,
      },
    });
  }

  async stock(id: string, tenantId: string, type: string, quantity: number, remark?: string) {
    const item = await this.prisma.inventoryItem.findFirst({ where: { id, tenantId } });
    if (!item) throw new NotFoundException();
    const delta = type === 'out' ? -Math.abs(quantity) : Math.abs(quantity);
    const next = item.quantity + delta;
    if (next < 0) throw new BadRequestException('库存不足');
    await this.prisma.inventoryStockLog.create({
      data: { itemId: id, type, quantity: Math.abs(quantity), remark },
    });
    return this.prisma.inventoryItem.update({ where: { id }, data: { quantity: next } });
  }

  async deleteItem(id: string, tenantId: string) {
    const item = await this.prisma.inventoryItem.findFirst({ where: { id, tenantId } });
    if (!item) throw new NotFoundException();
    return this.prisma.inventoryItem.delete({ where: { id } });
  }

  lowStock(tenantId: string) {
    return this.prisma.inventoryItem.findMany({ where: { tenantId } }).then((items) =>
      items.filter((i) => i.quantity <= i.lowStock),
    );
  }

  listMaintenance(tenantId: string) {
    return this.prisma.maintenanceOrder.findMany({
      where: { tenantId },
      orderBy: { createdAt: 'desc' },
    });
  }

  createMaintenance(tenantId: string, data: any) {
    return this.prisma.maintenanceOrder.create({
      data: {
        tenantId,
        title: data.title,
        location: data.location,
        description: data.description,
        assignee: data.assignee,
        status: 'pending',
      },
    });
  }

  async updateMaintenance(id: string, tenantId: string, data: any) {
    const row = await this.prisma.maintenanceOrder.findFirst({ where: { id, tenantId } });
    if (!row) throw new NotFoundException();
    return this.prisma.maintenanceOrder.update({
      where: { id },
      data: {
        status: data.status,
        assignee: data.assignee,
        completedAt: data.status === 'done' ? new Date() : row.completedAt,
        description: data.description,
      },
    });
  }
}
