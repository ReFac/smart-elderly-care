import { Body, Controller, Delete, Get, Param, Patch, Post, Req, UseGuards } from '@nestjs/common';
import { JwtAuthGuard } from '../auth/jwt-auth.guard';
import { ToursService } from './tours.service';

@Controller('tours')
export class ToursController {
  constructor(private tours: ToursService) {}

  /** 公开：手机 / 微信公众号房态导览 */
  @Get('public')
  publicList() {
    return this.tours.publicList();
  }

  @Get('public/:id')
  publicGet(@Param('id') id: string) {
    return this.tours.get(id);
  }

  @UseGuards(JwtAuthGuard)
  @Get()
  list(@Req() req: any) {
    return this.tours.list(req.user.tenantId);
  }

  @UseGuards(JwtAuthGuard)
  @Get(':id')
  get(@Param('id') id: string, @Req() req: any) {
    return this.tours.get(id, req.user.tenantId);
  }

  @UseGuards(JwtAuthGuard)
  @Post()
  create(@Body() body: any, @Req() req: any) {
    return this.tours.create(req.user.tenantId, body);
  }

  @UseGuards(JwtAuthGuard)
  @Patch(':id')
  update(@Param('id') id: string, @Body() body: any, @Req() req: any) {
    return this.tours.update(id, req.user.tenantId, body);
  }

  @UseGuards(JwtAuthGuard)
  @Post(':id/hotspots')
  hotspot(@Param('id') id: string, @Body() body: any, @Req() req: any) {
    return this.tours.addHotspot(id, req.user.tenantId, body);
  }

  @UseGuards(JwtAuthGuard)
  @Delete(':id')
  remove(@Param('id') id: string, @Req() req: any) {
    return this.tours.remove(id, req.user.tenantId);
  }
}
