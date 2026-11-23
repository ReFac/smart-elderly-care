import { Body, Controller, Delete, Get, Param, Patch, Post, Query, Req, UseGuards } from '@nestjs/common';
import { JwtAuthGuard } from '../auth/jwt-auth.guard';
import { HrService } from './hr.service';

@Controller('hr')
@UseGuards(JwtAuthGuard)
export class HrController {
  constructor(private hr: HrService) {}

  @Get('employees')
  employees(@Req() req: any) {
    return this.hr.listEmployees(req.user.tenantId);
  }

  @Post('employees')
  createEmployee(@Body() body: any, @Req() req: any) {
    return this.hr.createEmployee(req.user.tenantId, body);
  }

  @Patch('employees/:id')
  updateEmployee(@Param('id') id: string, @Body() body: any, @Req() req: any) {
    return this.hr.updateEmployee(id, req.user.tenantId, body);
  }

  @Get('shifts')
  shifts(@Req() req: any, @Query('from') from?: string, @Query('to') to?: string) {
    return this.hr.listShifts(req.user.tenantId, from, to);
  }

  @Post('shifts')
  createShift(@Body() body: any, @Req() req: any) {
    return this.hr.createShift(req.user.tenantId, body);
  }

  @Delete('shifts/:id')
  deleteShift(@Param('id') id: string, @Req() req: any) {
    return this.hr.deleteShift(id, req.user.tenantId);
  }

  @Get('attendance')
  attendance(@Req() req: any) {
    return this.hr.listAttendance(req.user.tenantId);
  }

  @Post('attendance/check-in')
  checkIn(@Body() body: any, @Req() req: any) {
    return this.hr.checkIn(body.employeeId || req.user.userId, req.user.tenantId, body.note);
  }

  @Post('attendance/:id/check-out')
  checkOut(@Param('id') id: string, @Req() req: any) {
    return this.hr.checkOut(id, req.user.tenantId);
  }

  @Get('performance')
  performance(@Req() req: any) {
    return this.hr.listPerformance(req.user.tenantId);
  }

  @Post('performance/compute')
  compute(@Body() body: any, @Req() req: any) {
    const period = body.period || new Date().toISOString().slice(0, 7);
    return this.hr.computePerformance(req.user.tenantId, period);
  }
}
