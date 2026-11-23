import { Module } from '@nestjs/common';
import { ConfigModule } from '@nestjs/config';
import { ScheduleModule } from '@nestjs/schedule';
import { PrismaModule } from './prisma/prisma.module';
import { AuthModule } from './auth/auth.module';
import { OrgModule } from './org/org.module';
import { EldersModule } from './elders/elders.module';
import { CareModule } from './care/care.module';
import { BillingModule } from './billing/billing.module';
import { MealsModule } from './meals/meals.module';
import { DashboardModule } from './dashboard/dashboard.module';
import { SettingsModule } from './settings/settings.module';
import { AiModule } from './ai/ai.module';
import { PaymentModule } from './payment/payment.module';
import { GpsModule } from './gps/gps.module';
import { PlaceholdersModule } from './placeholders/placeholders.module';
import { UploadModule } from './upload/upload.module';

@Module({
  imports: [
    ConfigModule.forRoot({ isGlobal: true }),
    ScheduleModule.forRoot(),
    PrismaModule,
    AuthModule,
    OrgModule,
    EldersModule,
    CareModule,
    BillingModule,
    MealsModule,
    DashboardModule,
    SettingsModule,
    AiModule,
    PaymentModule,
    GpsModule,
    PlaceholdersModule,
    UploadModule,
  ],
})
export class AppModule {}
