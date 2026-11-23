import { Body, Controller, Get, Param, Post, UseGuards } from '@nestjs/common';
import { GpsService } from './gps.service';
import { JwtAuthGuard } from '../auth/jwt-auth.guard';

@Controller('gps')
export class GpsController {
  constructor(private gps: GpsService) {}

  /** Device webhook — auth can be tightened later with device tokens. */
  @Post('webhook')
  webhook(
    @Body()
    body: { elderId: string; deviceId: string; lat: number; lng: number; recordedAt?: string },
  ) {
    return this.gps.ingest(body);
  }

  @UseGuards(JwtAuthGuard)
  @Get('elders/:elderId/latest')
  latest(@Param('elderId') elderId: string) {
    return this.gps.latest(elderId);
  }
}
