import { Module } from '@nestjs/common';
import { ClinicalIntelController } from './clinical-intel.controller';
import { ClinicalIntelService } from './clinical-intel.service';

@Module({
  controllers: [ClinicalIntelController],
  providers: [ClinicalIntelService],
  exports: [ClinicalIntelService],
})
export class ClinicalIntelModule {}
