import { BadRequestException, Injectable, NotFoundException } from '@nestjs/common';
import { PrismaService } from '../prisma/prisma.service';

@Injectable()
export class BillingService {
  constructor(private prisma: PrismaService) {}

  listFeeItems(tenantId: string) {
    return this.prisma.feeItem.findMany({ where: { tenantId, active: true }, orderBy: { code: 'asc' } });
  }

  createFeeItem(tenantId: string, data: any) {
    return this.prisma.feeItem.create({
      data: {
        tenantId,
        code: data.code,
        name: data.name,
        unit: data.unit || '月',
        defaultPrice: data.defaultPrice || 0,
        category: data.category || 'other',
      },
    });
  }

  listPriceRules(tenantId: string) {
    return this.prisma.priceRule.findMany({ where: { tenantId } });
  }

  listBills(tenantId: string, status?: string, elderId?: string) {
    return this.prisma.bill.findMany({
      where: {
        elder: { tenantId },
        ...(status ? { status } : {}),
        ...(elderId ? { elderId } : {}),
      },
      include: {
        elder: { select: { id: true, name: true, careLevel: true } },
        lines: true,
        payments: true,
      },
      orderBy: { createdAt: 'desc' },
    });
  }

  async getBill(id: string, tenantId: string) {
    const bill = await this.prisma.bill.findFirst({
      where: { id, elder: { tenantId } },
      include: { elder: true, lines: true, payments: true },
    });
    if (!bill) throw new NotFoundException('账单不存在');
    return bill;
  }

  async generateMonthlyBills(tenantId: string, year: number, month: number) {
    const periodStart = new Date(year, month - 1, 1);
    const periodEnd = new Date(year, month, 0, 23, 59, 59);
    const elders = await this.prisma.elder.findMany({
      where: { tenantId, status: 'active' },
    });
    const rules = await this.prisma.priceRule.findMany({ where: { tenantId } });
    const feeItems = await this.prisma.feeItem.findMany({ where: { tenantId } });
    const feeMap = Object.fromEntries(feeItems.map((f) => [f.code, f]));
    const created: any[] = [];

    for (const elder of elders) {
      const exists = await this.prisma.bill.findFirst({
        where: { elderId: elder.id, periodStart, periodEnd },
      });
      if (exists) continue;

      const elderRules = rules.filter((r) => r.careLevel === elder.careLevel);
      const lines = elderRules.map((r) => {
        const fee = feeMap[r.feeItemCode];
        return {
          feeCode: r.feeItemCode,
          feeName: fee?.name || r.feeItemCode,
          quantity: 1,
          unitPrice: r.price,
          amount: r.price,
        };
      });
      if (!lines.length) {
        lines.push(
          ...feeItems
            .filter((f) => ['bed', 'care', 'meal'].includes(f.category))
            .map((f) => ({
              feeCode: f.code,
              feeName: f.name,
              quantity: 1,
              unitPrice: f.defaultPrice,
              amount: f.defaultPrice,
            })),
        );
      }
      const totalAmount = lines.reduce((s, l) => s + l.amount, 0);
      const bill = await this.prisma.bill.create({
        data: {
          elderId: elder.id,
          periodStart,
          periodEnd,
          totalAmount,
          paidAmount: 0,
          status: 'unpaid',
          lines: { create: lines },
        },
        include: { lines: true, elder: { select: { id: true, name: true } } },
      });
      created.push(bill);
    }
    return { count: created.length, bills: created };
  }

  async pay(billId: string, tenantId: string, data: any) {
    const bill = await this.getBill(billId, tenantId);
    const amount = Number(data.amount);
    if (!(amount > 0)) throw new BadRequestException('金额无效');
    const paidAmount = bill.paidAmount + amount;
    let status = 'partial';
    if (paidAmount >= bill.totalAmount) status = 'paid';
    else if (new Date() > bill.periodEnd) status = 'overdue';
    const payment = await this.prisma.payment.create({
      data: {
        billId,
        amount,
        method: data.method || 'cash',
        remark: data.remark,
      },
    });
    const updated = await this.prisma.bill.update({
      where: { id: billId },
      data: { paidAmount, status },
      include: { lines: true, payments: true },
    });
    return { payment, bill: updated };
  }

  async addDeposit(elderId: string, tenantId: string, data: any) {
    const elder = await this.prisma.elder.findFirst({ where: { id: elderId, tenantId } });
    if (!elder) throw new NotFoundException('老人不存在');
    const deposit = await this.prisma.deposit.create({
      data: {
        elderId,
        amount: data.amount,
        type: data.type || 'in',
        remark: data.remark,
      },
    });
    const delta = data.type === 'out' ? -Math.abs(data.amount) : Math.abs(data.amount);
    await this.prisma.elder.update({
      where: { id: elderId },
      data: { depositAmount: elder.depositAmount + delta },
    });
    return deposit;
  }

  async addWaiver(elderId: string, tenantId: string, data: any) {
    const elder = await this.prisma.elder.findFirst({ where: { id: elderId, tenantId } });
    if (!elder) throw new NotFoundException('老人不存在');
    return this.prisma.waiver.create({
      data: { elderId, amount: data.amount, reason: data.reason },
    });
  }

  overdue(tenantId: string) {
    return this.listBills(tenantId, 'unpaid').then(async (unpaid) => {
      const overdueAlso = await this.listBills(tenantId, 'overdue');
      const partial = await this.listBills(tenantId, 'partial');
      return [...overdueAlso, ...unpaid, ...partial].filter(
        (b) => b.paidAmount < b.totalAmount,
      );
    });
  }
}
