import { Body, Controller, Get, Param, Post, Query, Req, UseGuards } from '@nestjs/common';
import { BillingService } from './billing.service';
import { JwtAuthGuard } from '../auth/jwt-auth.guard';

@Controller('billing')
@UseGuards(JwtAuthGuard)
export class BillingController {
  constructor(private billing: BillingService) {}

  @Get('fee-items')
  feeItems(@Req() req: any) {
    return this.billing.listFeeItems(req.user.tenantId);
  }

  @Post('fee-items')
  createFee(@Body() body: any, @Req() req: any) {
    return this.billing.createFeeItem(req.user.tenantId, body);
  }

  @Get('price-rules')
  rules(@Req() req: any) {
    return this.billing.listPriceRules(req.user.tenantId);
  }

  @Get('bills')
  bills(@Req() req: any, @Query('status') status?: string, @Query('elderId') elderId?: string) {
    return this.billing.listBills(req.user.tenantId, status, elderId);
  }

  @Get('bills/overdue')
  overdue(@Req() req: any) {
    return this.billing.overdue(req.user.tenantId);
  }

  @Get('bills/:id')
  bill(@Param('id') id: string, @Req() req: any) {
    return this.billing.getBill(id, req.user.tenantId);
  }

  @Post('bills/generate')
  generate(@Body() body: any, @Req() req: any) {
    const now = new Date();
    return this.billing.generateMonthlyBills(
      req.user.tenantId,
      body.year || now.getFullYear(),
      body.month || now.getMonth() + 1,
    );
  }

  @Post('bills/:id/pay')
  pay(@Param('id') id: string, @Body() body: any, @Req() req: any) {
    return this.billing.pay(id, req.user.tenantId, body);
  }

  @Post('elders/:elderId/deposits')
  deposit(@Param('elderId') elderId: string, @Body() body: any, @Req() req: any) {
    return this.billing.addDeposit(elderId, req.user.tenantId, body);
  }

  @Post('elders/:elderId/waivers')
  waiver(@Param('elderId') elderId: string, @Body() body: any, @Req() req: any) {
    return this.billing.addWaiver(elderId, req.user.tenantId, body);
  }
}
