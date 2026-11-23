import { Module } from '@nestjs/common';
import { LtcController } from './ltc.controller';
import { LtcService } from './ltc.service';

@Module({
  controllers: [LtcController],
  providers: [LtcService],
  exports: [LtcService],
})
export class LtcModule {}
