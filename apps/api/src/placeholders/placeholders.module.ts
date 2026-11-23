import { Module } from '@nestjs/common';
import { PlaceholdersController } from './placeholders.controller';

@Module({
  controllers: [PlaceholdersController],
})
export class PlaceholdersModule {}
