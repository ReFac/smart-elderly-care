import { Body, Controller, Get, Param, Patch, Post, Query, Req, UseGuards } from '@nestjs/common';
import { CareService } from './care.service';
import { JwtAuthGuard } from '../auth/jwt-auth.guard';

@Controller('care')
@UseGuards(JwtAuthGuard)
export class CareController {
  constructor(private care: CareService) {}

  @Get('plans')
  plans(@Req() req: any) {
    return this.care.listPlans(req.user.tenantId);
  }

  @Post('plans/:elderId/generate')
  generatePlan(@Param('elderId') elderId: string, @Req() req: any) {
    return this.care.generatePlan(elderId, req.user.tenantId);
  }

  @Post('tasks/generate-today')
  generateTasks(@Req() req: any) {
    return this.care.generateTodayTasks(req.user.tenantId);
  }

  @Get('tasks')
  tasks(@Req() req: any, @Query('date') date?: string, @Query('status') status?: string) {
    return this.care.listTasks(req.user.tenantId, date, status);
  }

  @Post('tasks/:id/checkin')
  checkin(@Param('id') id: string, @Body() body: any, @Req() req: any) {
    return this.care.checkin(id, req.user.userId, req.user.tenantId, body);
  }

  @Get('orders')
  orders(@Req() req: any) {
    return this.care.listOrders(req.user.tenantId);
  }

  @Post('orders')
  createOrder(@Body() body: any, @Req() req: any) {
    return this.care.createOrder(req.user.tenantId, req.user.userId, body);
  }

  @Patch('orders/:id')
  updateOrder(@Param('id') id: string, @Body() body: any, @Req() req: any) {
    return this.care.updateOrder(id, req.user.tenantId, body);
  }

  @Get('visits')
  visits(@Req() req: any) {
    return this.care.listVisits(req.user.tenantId);
  }

  @Post('visits')
  createVisit(@Body() body: any, @Req() req: any) {
    return this.care.createVisit(req.user.tenantId, body);
  }
}
