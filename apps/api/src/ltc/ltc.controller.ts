import { Body, Controller, Get, Param, Patch, Post, Query, Req, UseGuards } from '@nestjs/common';
import { JwtAuthGuard } from '../auth/jwt-auth.guard';
import { LtcService } from './ltc.service';

@Controller('ltc')
@UseGuards(JwtAuthGuard)
export class LtcController {
  constructor(private ltc: LtcService) {}

  @Get('assessments')
  assessments(@Req() req: any) {
    return this.ltc.listAssessments(req.user.tenantId);
  }

  @Post('assessments')
  createAssessment(@Body() body: any, @Req() req: any) {
    return this.ltc.createAssessment(req.user.tenantId, body);
  }

  @Patch('assessments/:id')
  updateAssessment(@Param('id') id: string, @Body() body: any, @Req() req: any) {
    return this.ltc.updateAssessment(id, req.user.tenantId, body);
  }

  @Get('items')
  items(@Req() req: any) {
    return this.ltc.listItems(req.user.tenantId);
  }

  @Post('items')
  createItem(@Body() body: any, @Req() req: any) {
    return this.ltc.createItem(req.user.tenantId, body);
  }

  @Get('records')
  records(@Req() req: any) {
    return this.ltc.listRecords(req.user.tenantId);
  }

  @Post('records')
  createRecord(@Body() body: any, @Req() req: any) {
    return this.ltc.createRecord(req.user.tenantId, body);
  }

  @Get('reconciliations')
  reconciliations(@Req() req: any) {
    return this.ltc.listReconciliations(req.user.tenantId);
  }

  @Post('reconciliations')
  createRecon(@Body() body: any, @Req() req: any) {
    return this.ltc.createReconciliation(req.user.tenantId, body);
  }

  @Patch('reconciliations/:id')
  updateRecon(@Param('id') id: string, @Body() body: any, @Req() req: any) {
    return this.ltc.updateReconciliation(id, req.user.tenantId, body);
  }

  @Get('export')
  exportPkg(@Req() req: any, @Query('elderId') elderId: string, @Query('period') period: string) {
    return this.ltc.exportPackage(req.user.tenantId, elderId, period || new Date().toISOString().slice(0, 7));
  }
}
