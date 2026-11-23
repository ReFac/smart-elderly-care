import { Body, Controller, Delete, Get, Param, Post, Put, Query, Req, UseGuards } from '@nestjs/common';
import { JwtAuthGuard } from '../auth/jwt-auth.guard';
import { ControlPlaneService } from './control-plane.service';

@Controller('control')
@UseGuards(JwtAuthGuard)
export class ControlPlaneController {
  constructor(private cp: ControlPlaneService) {}

  @Get('snapshot')
  snapshot(@Req() req: any) {
    return this.cp.snapshot(req.user.tenantId);
  }

  @Get('variables')
  variables(@Req() req: any, @Query('group') group?: string) {
    return this.cp.listVariables(req.user.tenantId, group);
  }

  @Put('variables')
  upsertVar(@Body() body: any, @Req() req: any) {
    return this.cp.upsertVariable(req.user.tenantId, body);
  }

  @Delete('variables/:key')
  delVar(@Param('key') key: string, @Req() req: any) {
    return this.cp.deleteVariable(req.user.tenantId, decodeURIComponent(key));
  }

  @Get('services')
  services(@Req() req: any) {
    return this.cp.listServices(req.user.tenantId);
  }

  @Put('services')
  upsertSvc(@Body() body: any, @Req() req: any) {
    return this.cp.upsertService(req.user.tenantId, body);
  }

  @Post('services/:code/probe')
  probe(@Param('code') code: string, @Req() req: any) {
    return this.cp.probeService(req.user.tenantId, code);
  }

  @Get('apis')
  apis(@Req() req: any, @Query('audience') audience?: string) {
    return this.cp.listApis(req.user.tenantId, audience);
  }

  @Put('apis')
  upsertApi(@Body() body: any, @Req() req: any) {
    return this.cp.upsertApi(req.user.tenantId, body);
  }
}
