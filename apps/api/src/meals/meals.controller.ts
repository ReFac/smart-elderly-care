import { Body, Controller, Get, Post, Query, Req, UseGuards } from '@nestjs/common';
import { MealsService } from './meals.service';
import { JwtAuthGuard } from '../auth/jwt-auth.guard';

@Controller('meals')
@UseGuards(JwtAuthGuard)
export class MealsController {
  constructor(private meals: MealsService) {}

  @Get()
  list(@Req() req: any, @Query('from') from?: string, @Query('to') to?: string) {
    return this.meals.list(req.user.tenantId, from, to);
  }

  @Get('today')
  today(@Req() req: any) {
    return this.meals.today(req.user.tenantId);
  }

  @Post()
  upsert(@Body() body: any, @Req() req: any) {
    return this.meals.upsert(req.user.tenantId, body);
  }
}
