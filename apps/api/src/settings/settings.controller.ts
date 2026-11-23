import { Body, Controller, Get, Patch, Post, Req, UseGuards } from '@nestjs/common';
import { SettingsService } from './settings.service';
import { JwtAuthGuard } from '../auth/jwt-auth.guard';

@Controller('settings')
@UseGuards(JwtAuthGuard)
export class SettingsController {
  constructor(private settings: SettingsService) {}

  @Get('flags')
  flags(@Req() req: any) {
    return this.settings.flags(req.user.tenantId);
  }

  @Patch('flags')
  setFlag(@Body() body: { key: string; enabled: boolean }, @Req() req: any) {
    return this.settings.setFlag(req.user.tenantId, body.key, body.enabled);
  }

  @Get('ai')
  ai(@Req() req: any) {
    return this.settings.getAiConfig(req.user.tenantId);
  }

  @Post('ai')
  saveAi(@Body() body: any, @Req() req: any) {
    return this.settings.upsertAiConfig(req.user.tenantId, body);
  }
}
