import { Body, Controller, Get, Param, Post, Req, UseGuards } from '@nestjs/common';
import { JwtAuthGuard } from '../auth/jwt-auth.guard';
import { AgentBridgeService } from './agent-bridge.service';
import { AgentConsoleService } from './console.service';

@Controller('agent')
@UseGuards(JwtAuthGuard)
export class AgentBridgeController {
  constructor(
    private agent: AgentBridgeService,
    private console: AgentConsoleService,
  ) {}

  /** Codex 风格侧栏对话 */
  @Post('console/chat')
  consoleChat(@Body() body: any, @Req() req: any) {
    return this.console.chat(req.user.tenantId, req.user, body.message, body.contextPath);
  }

  /** 高权限执行：需密码 + 变更甄别后的 action 草案 */
  @Post('console/execute')
  consoleExecute(@Body() body: any, @Req() req: any) {
    return this.console.execute(req.user.tenantId, req.user, body);
  }

  @Get('manifest')
  manifest() {
    return this.agent.manifest();
  }

  @Get('audit')
  audit() {
    return this.agent.audit();
  }

  @Get('reviews')
  reviews() {
    return this.agent.reviews();
  }

  @Post('fusion')
  fusion(@Body() body: any) {
    return this.agent.post('/v1/fusion/decide', body);
  }

  @Post('care/voice')
  careVoice(@Body() body: any) {
    return this.agent.post('/v1/care/voice', body);
  }

  @Post('meeting')
  meeting(@Body() body: any) {
    return this.agent.post('/v1/meeting/summarize', body);
  }

  @Post('typeless')
  typeless(@Body() body: any) {
    return this.agent.post('/v1/typeless', body);
  }

  @Post('health/auto')
  health(@Body() body: any) {
    return this.agent.post('/v1/health/auto', body);
  }

  @Post('acoustic/ingest')
  acoustic(@Body() body: any) {
    return this.agent.post('/v1/acoustic/ingest', body);
  }

  @Post('feedback')
  feedback(@Body() body: any) {
    return this.agent.post('/v1/alerts/feedback', body);
  }

  @Post('reviews/:id/resolve')
  resolve(@Param('id') id: string, @Body() body: any) {
    return this.agent.post(`/v1/reviews/${id}/resolve`, body);
  }
}
