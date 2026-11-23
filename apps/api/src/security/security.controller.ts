import { Body, Controller, Get, Param, Post, Query, Req, UseGuards } from '@nestjs/common';
import { JwtAuthGuard } from '../auth/jwt-auth.guard';
import { SecurityService } from './security.service';

@Controller('security')
export class SecurityController {
  constructor(private security: SecurityService) {}

  @UseGuards(JwtAuthGuard)
  @Get('alerts')
  alerts(@Req() req: any, @Query('status') status?: string) {
    return this.security.listAlerts(req.user.tenantId, status);
  }

  @UseGuards(JwtAuthGuard)
  @Post('alerts')
  create(@Body() body: any, @Req() req: any) {
    return this.security.createAlert(req.user.tenantId, body);
  }

  @UseGuards(JwtAuthGuard)
  @Post('alerts/:id/handle')
  handle(@Param('id') id: string, @Req() req: any, @Body() body: any) {
    return this.security.handleAlert(id, req.user.tenantId, req.user.name, body.status || 'handled');
  }

  @UseGuards(JwtAuthGuard)
  @Post('risks/scan')
  scan(@Req() req: any) {
    return this.security.scanRisks(req.user.tenantId);
  }

  @UseGuards(JwtAuthGuard)
  @Get('access-logs')
  access(@Req() req: any) {
    return this.security.listAccess(req.user.tenantId);
  }

  @UseGuards(JwtAuthGuard)
  @Post('access-logs')
  createAccess(@Body() body: any, @Req() req: any) {
    return this.security.createAccess(req.user.tenantId, body);
  }

  /** Device webhook — tenantId required in body for MVP. */
  @Post('hardware/webhook')
  hardware(@Body() body: any) {
    return this.security.ingestHardware(body.tenantId, body);
  }
}
