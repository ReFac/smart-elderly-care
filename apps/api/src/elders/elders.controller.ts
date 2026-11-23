import { Body, Controller, Get, Param, Patch, Post, Query, Req, UseGuards } from '@nestjs/common';
import { EldersService } from './elders.service';
import { JwtAuthGuard } from '../auth/jwt-auth.guard';

@Controller('elders')
@UseGuards(JwtAuthGuard)
export class EldersController {
  constructor(private elders: EldersService) {}

  @Get()
  list(@Req() req: any, @Query('q') q?: string) {
    return this.elders.list(req.user.tenantId, q);
  }

  @Get('contracts/expiring')
  expiring(@Req() req: any, @Query('days') days?: string) {
    return this.elders.expiringContracts(req.user.tenantId, days ? Number(days) : 30);
  }

  @Get(':id')
  get(@Param('id') id: string, @Req() req: any) {
    return this.elders.get(id, req.user.tenantId);
  }

  @Post()
  create(@Body() body: any, @Req() req: any) {
    return this.elders.create(req.user.tenantId, body);
  }

  @Patch(':id')
  update(@Param('id') id: string, @Body() body: any, @Req() req: any) {
    return this.elders.update(id, req.user.tenantId, body);
  }

  @Post(':id/change-bed')
  changeBed(@Param('id') id: string, @Body() body: any, @Req() req: any) {
    return this.elders.changeBed(id, req.user.tenantId, body.toBedId, body.reason, req.user.name);
  }

  @Post(':id/contracts')
  contract(@Param('id') id: string, @Body() body: any, @Req() req: any) {
    return this.elders.addContract(id, req.user.tenantId, body);
  }

  @Post(':id/emotions')
  emotion(@Param('id') id: string, @Body() body: any, @Req() req: any) {
    return this.elders.addEmotion(id, req.user.tenantId, body);
  }

  @Post(':id/contacts')
  contact(@Param('id') id: string, @Body() body: any, @Req() req: any) {
    return this.elders.addContact(id, req.user.tenantId, body);
  }
}
