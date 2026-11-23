import { Body, Controller, Get, Post, Query, UseGuards } from '@nestjs/common';
import { JwtAuthGuard } from '../auth/jwt-auth.guard';
import { ExtensionsService } from './extensions.service';

@Controller('extensions')
@UseGuards(JwtAuthGuard)
export class ExtensionsController {
  constructor(private ext: ExtensionsService) {}

  @Get('catalog')
  catalog() {
    return this.ext.catalog();
  }

  @Get('search')
  search(@Query('q') q = '') {
    return this.ext.search(q);
  }

  @Get('dynamic')
  dynamic() {
    return this.ext.listDynamic();
  }

  @Post('register')
  register(@Body() body: any) {
    return this.ext.register(body);
  }

  @Post('learning/correct')
  learn(@Body() body: any) {
    return this.ext.learnFromCorrection(body);
  }

  @Get('learning/stats')
  learningStats() {
    return this.ext.learningStats();
  }

  @Get('learning/noise')
  noise(@Query('limit') limit?: string) {
    return this.ext.noiseBankSample(limit ? Number(limit) : 20);
  }
}
