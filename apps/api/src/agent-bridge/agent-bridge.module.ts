import { Module } from '@nestjs/common';
import { AgentBridgeController } from './agent-bridge.controller';
import { AgentBridgeService } from './agent-bridge.service';

@Module({
  controllers: [AgentBridgeController],
  providers: [AgentBridgeService],
})
export class AgentBridgeModule {}
