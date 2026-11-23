import { Body, Controller, Get, Param, Patch, Query, Req, UseGuards } from '@nestjs/common';
import { OrgService } from './org.service';
import { JwtAuthGuard } from '../auth/jwt-auth.guard';

@Controller('org')
@UseGuards(JwtAuthGuard)
export class OrgController {
  constructor(private org: OrgService) {}

  @Get('buildings')
  buildings(@Req() req: any) {
    return this.org.listBuildings(req.user.tenantId);
  }

  @Get('floors/:id')
  floor(@Param('id') id: string, @Req() req: any) {
    return this.org.floorView(id, req.user.tenantId);
  }

  @Patch('floors/:id/plan')
  plan(@Param('id') id: string, @Body('planImage') planImage: string, @Req() req: any) {
    return this.org.updateFloorPlan(id, req.user.tenantId, planImage);
  }

  @Get('beds/stats')
  stats(@Req() req: any) {
    return this.org.bedStats(req.user.tenantId);
  }

  @Get('beds')
  beds(@Req() req: any, @Query('status') status?: string) {
    return this.org.listBeds(req.user.tenantId, status);
  }

  @Patch('beds/:id/status')
  bedStatus(@Param('id') id: string, @Body('status') status: string, @Req() req: any) {
    return this.org.setBedStatus(id, req.user.tenantId, status);
  }
}
