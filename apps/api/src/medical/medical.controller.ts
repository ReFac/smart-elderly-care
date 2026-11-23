import { Body, Controller, Delete, Get, Param, Patch, Post, Query, Req, UseGuards } from '@nestjs/common';
import { JwtAuthGuard } from '../auth/jwt-auth.guard';
import { MedicalService } from './medical.service';

@Controller('medical')
@UseGuards(JwtAuthGuard)
export class MedicalController {
  constructor(private medical: MedicalService) {}

  @Get('vitals')
  vitals(@Req() req: any, @Query('elderId') elderId?: string) {
    return this.medical.listVitals(req.user.tenantId, elderId);
  }

  @Post('vitals')
  createVital(@Body() body: any, @Req() req: any) {
    return this.medical.createVital(req.user.tenantId, body);
  }

  @Delete('vitals/:id')
  deleteVital(@Param('id') id: string, @Req() req: any) {
    return this.medical.deleteVital(id, req.user.tenantId);
  }

  @Get('drugs')
  drugs(@Req() req: any) {
    return this.medical.listDrugs(req.user.tenantId);
  }

  @Post('drugs')
  createDrug(@Body() body: any, @Req() req: any) {
    return this.medical.createDrug(req.user.tenantId, body);
  }

  @Patch('drugs/:id')
  updateDrug(@Param('id') id: string, @Body() body: any, @Req() req: any) {
    return this.medical.updateDrug(id, req.user.tenantId, body);
  }

  @Post('drugs/:id/stock')
  stockDrug(@Param('id') id: string, @Body() body: any, @Req() req: any) {
    return this.medical.stockDrug(id, req.user.tenantId, body.type || 'in', Number(body.quantity), body.remark);
  }

  @Get('plans')
  plans(@Req() req: any) {
    return this.medical.listPlans(req.user.tenantId);
  }

  @Post('plans')
  createPlan(@Body() body: any, @Req() req: any) {
    return this.medical.createPlan(req.user.tenantId, body);
  }

  @Get('doses')
  doses(@Req() req: any, @Query('status') status?: string) {
    return this.medical.listDoses(req.user.tenantId, status);
  }

  @Post('doses/:id/give')
  giveDose(@Param('id') id: string, @Body() body: any, @Req() req: any) {
    return this.medical.giveDose(id, req.user.tenantId, req.user.userId, body);
  }

  @Get('adverse')
  adverse(@Req() req: any) {
    return this.medical.listAdverse(req.user.tenantId);
  }

  @Post('adverse')
  createAdverse(@Body() body: any, @Req() req: any) {
    return this.medical.createAdverse(req.user.tenantId, body);
  }

  @Get('exams')
  exams(@Req() req: any) {
    return this.medical.listExams(req.user.tenantId);
  }

  @Post('exams')
  createExam(@Body() body: any, @Req() req: any) {
    return this.medical.createExam(req.user.tenantId, body);
  }

  @Get('follow-ups')
  followUps(@Req() req: any) {
    return this.medical.listFollowUps(req.user.tenantId);
  }

  @Post('follow-ups')
  createFollowUp(@Body() body: any, @Req() req: any) {
    return this.medical.createFollowUp(req.user.tenantId, body);
  }

  @Get('orders')
  orders(@Req() req: any) {
    return this.medical.listOrders(req.user.tenantId);
  }

  @Post('orders')
  createOrder(@Body() body: any, @Req() req: any) {
    return this.medical.createOrder(req.user.tenantId, body);
  }

  @Patch('orders/:id')
  updateOrder(@Param('id') id: string, @Body() body: any, @Req() req: any) {
    return this.medical.updateOrder(id, req.user.tenantId, body);
  }

  @Get('referrals')
  referrals(@Req() req: any) {
    return this.medical.listReferrals(req.user.tenantId);
  }

  @Post('referrals')
  createReferral(@Body() body: any, @Req() req: any) {
    return this.medical.createReferral(req.user.tenantId, body);
  }

  @Patch('referrals/:id')
  updateReferral(@Param('id') id: string, @Body() body: any, @Req() req: any) {
    return this.medical.updateReferral(id, req.user.tenantId, body);
  }
}
