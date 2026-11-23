import { Body, Controller, Delete, Get, Param, Patch, Post, Query, Req, UseGuards } from '@nestjs/common';
import { JwtAuthGuard } from '../auth/jwt-auth.guard';
import { ReportsService } from './reports.service';

@Controller('reports')
@UseGuards(JwtAuthGuard)
export class ReportsController {
  constructor(private reports: ReportsService) {}

  @Get()
  list(@Req() req: any) {
    return this.reports.list(req.user.tenantId);
  }

  @Post()
  create(@Body() body: any, @Req() req: any) {
    return this.reports.create(req.user.tenantId, body);
  }

  @Post('generate/monthly')
  generate(@Body() body: any, @Req() req: any) {
    return this.reports.generateMonthly(req.user.tenantId, body.period);
  }

  @Get(':id/export')
  exportJson(@Param('id') id: string, @Req() req: any) {
    return this.reports.exportJson(id, req.user.tenantId);
  }

  @Patch(':id')
  update(@Param('id') id: string, @Body() body: any, @Req() req: any) {
    return this.reports.update(id, req.user.tenantId, body);
  }

  @Delete(':id')
  remove(@Param('id') id: string, @Req() req: any) {
    return this.reports.delete(id, req.user.tenantId);
  }
}
