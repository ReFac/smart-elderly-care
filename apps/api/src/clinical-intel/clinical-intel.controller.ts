import { Body, Controller, Get, Param, Post, Put, Query, Req, UseGuards } from '@nestjs/common';
import { JwtAuthGuard } from '../auth/jwt-auth.guard';
import { ClinicalIntelService } from './clinical-intel.service';

@Controller('clinical')
export class ClinicalIntelController {
  constructor(private clinical: ClinicalIntelService) {}

  /** 公开契约：便于 SOTA / 硬件厂商对接文档化发现 */
  @Get('contract')
  contract() {
    return this.clinical.contract();
  }

  @UseGuards(JwtAuthGuard)
  @Get('config')
  config(@Req() req: any) {
    return this.clinical.getConfig(req.user.tenantId);
  }

  @UseGuards(JwtAuthGuard)
  @Put('config')
  upsertConfig(@Body() body: any, @Req() req: any) {
    return this.clinical.upsertConfig(req.user.tenantId, body);
  }

  @UseGuards(JwtAuthGuard)
  @Get('devices')
  devices(@Req() req: any) {
    return this.clinical.listDevices(req.user.tenantId);
  }

  @UseGuards(JwtAuthGuard)
  @Put('devices')
  upsertDevice(@Body() body: any, @Req() req: any) {
    return this.clinical.upsertDevice(req.user.tenantId, body);
  }

  @UseGuards(JwtAuthGuard)
  @Get('prompts')
  prompts(@Req() req: any) {
    return this.clinical.listPrompts(req.user.tenantId);
  }

  @UseGuards(JwtAuthGuard)
  @Put('prompts')
  upsertPrompt(@Body() body: any, @Req() req: any) {
    return this.clinical.upsertPrompt(req.user.tenantId, body);
  }

  /** 麦克风网关 / Agent 推送声学事件 */
  @UseGuards(JwtAuthGuard)
  @Post('events/ingest')
  ingest(@Body() body: any, @Req() req: any) {
    return this.clinical.ingestEvent(req.user.tenantId, body);
  }

  @UseGuards(JwtAuthGuard)
  @Get('events')
  events(@Req() req: any, @Query('elderId') elderId?: string) {
    return this.clinical.listEvents(req.user.tenantId, elderId);
  }

  @UseGuards(JwtAuthGuard)
  @Post('events/:id/label')
  label(@Param('id') id: string, @Body() body: any, @Req() req: any) {
    return this.clinical.markEventNoise(req.user.tenantId, id, body.kind || 'false_positive', body.note);
  }

  @UseGuards(JwtAuthGuard)
  @Get('findings')
  findings(@Req() req: any, @Query('elderId') elderId: string) {
    return this.clinical.listFindings(req.user.tenantId, elderId);
  }

  @UseGuards(JwtAuthGuard)
  @Post('prediagnosis/generate')
  generate(@Body() body: any, @Req() req: any) {
    return this.clinical.generatePrediagnosis(req.user.tenantId, body.elderId, {
      modelId: body.modelId,
      generatedBy: req.user.userId || req.user.username,
    });
  }

  @UseGuards(JwtAuthGuard)
  @Get('prediagnosis')
  reports(@Req() req: any, @Query('elderId') elderId?: string) {
    return this.clinical.listReports(req.user.tenantId, elderId);
  }

  @UseGuards(JwtAuthGuard)
  @Get('prediagnosis/:id')
  report(@Param('id') id: string, @Req() req: any) {
    return this.clinical.getReport(req.user.tenantId, id);
  }

  @UseGuards(JwtAuthGuard)
  @Get('pushes')
  pushes(@Req() req: any, @Query('audience') audience?: string) {
    return this.clinical.listPushes(req.user.tenantId, audience);
  }

  @UseGuards(JwtAuthGuard)
  @Post('pushes/:id/approve-family')
  approve(@Param('id') id: string, @Body() body: any, @Req() req: any) {
    return this.clinical.approveFamilyPush(req.user.tenantId, id, req.user.userId || req.user.sub, body);
  }

  @UseGuards(JwtAuthGuard)
  @Post('pushes/:id/reject-family')
  reject(@Param('id') id: string, @Body() body: any, @Req() req: any) {
    return this.clinical.rejectFamilyPush(req.user.tenantId, id, req.user.userId || req.user.sub, body?.reason);
  }
}
