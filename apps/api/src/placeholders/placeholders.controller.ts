import { Controller, Get, UseGuards } from '@nestjs/common';
import { JwtAuthGuard } from '../auth/jwt-auth.guard';

@Controller()
@UseGuards(JwtAuthGuard)
export class PlaceholdersController {
  private stub(module: string) {
    return {
      module,
      status: 'stub',
      message: `${module} 模块已预留接口，将在后续版本实现`,
    };
  }

  @Get('medical/stub')
  medical() {
    return this.stub('医护健康/发药');
  }

  @Get('ltc/stub')
  ltc() {
    return this.stub('长护险');
  }

  @Get('inventory/stub')
  inventory() {
    return this.stub('后勤物资');
  }

  @Get('hr/stub')
  hr() {
    return this.stub('人事排班');
  }

  @Get('security/stub')
  security() {
    return this.stub('安防告警');
  }

  @Get('reports/stub')
  reports() {
    return this.stub('民政报表报送');
  }
}
