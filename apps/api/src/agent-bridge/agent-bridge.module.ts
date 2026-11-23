import { Module } from '@nestjs/common';
import { AuthModule } from '../auth/auth.module';
import { ControlPlaneModule } from '../control-plane/control-plane.module';
import { ClinicalIntelModule } from '../clinical-intel/clinical-intel.module';
import { AgentBridgeController } from './agent-bridge.controller';
import { AgentBridgeService } from './agent-bridge.service';
import { AgentConsoleService } from './console.service';

@Module({
  imports: [AuthModule, ControlPlaneModule, ClinicalIntelModule],
  controllers: [AgentBridgeController],
  providers: [AgentBridgeService, AgentConsoleService],
})
export class AgentBridgeModule {}
