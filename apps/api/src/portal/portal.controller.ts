import { Controller, Get, Req, UseGuards } from '@nestjs/common';
import { JwtAuthGuard } from '../auth/jwt-auth.guard';
import { PortalService } from './portal.service';

@Controller('portal')
@UseGuards(JwtAuthGuard)
export class PortalController {
  constructor(private portal: PortalService) {}

  /** 用户/家属端首页聚合 — 手机 / 微信公众号优先 */
  @Get('user/home')
  userHome(@Req() req: any) {
    return this.portal.userHome(req.user.tenantId, req.user.userId);
  }

  /** 员工端首页聚合 — 护理员/护士移动端 */
  @Get('employee/home')
  employeeHome(@Req() req: any) {
    return this.portal.employeeHome(req.user.tenantId, req.user.userId);
  }
}
