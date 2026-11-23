import { Body, Controller, Post, UseGuards } from '@nestjs/common';
import { PaymentService } from './payment.service';
import { JwtAuthGuard } from '../auth/jwt-auth.guard';

@Controller('payment')
@UseGuards(JwtAuthGuard)
export class PaymentController {
  constructor(private payment: PaymentService) {}

  @Post('checkout')
  checkout(@Body() body: { billId: string; amount: number; channel?: string }) {
    return this.payment.createCheckout(body.billId, body.amount, body.channel);
  }
}
