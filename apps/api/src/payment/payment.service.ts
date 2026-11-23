import { Injectable } from '@nestjs/common';

export interface PaymentProvider {
  createCheckout(billId: string, amount: number, channel: string): Promise<{ status: string; payUrl?: string }>;
}

class StubPaymentProvider implements PaymentProvider {
  async createCheckout(billId: string, amount: number, channel: string) {
    return {
      status: 'not_implemented',
      message: `支付通道 ${channel} 已预留，账单 ${billId} 金额 ${amount}，后续对接支付宝/微信/云闪付`,
    } as any;
  }
}

@Injectable()
export class PaymentService {
  private provider: PaymentProvider = new StubPaymentProvider();

  createCheckout(billId: string, amount: number, channel = 'wechat') {
    return this.provider.createCheckout(billId, amount, channel);
  }
}
