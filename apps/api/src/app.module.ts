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
import { UploadModule } from './upload/upload.module';
import { MedicalModule } from './medical/medical.module';
import { LtcModule } from './ltc/ltc.module';
import { InventoryModule } from './inventory/inventory.module';
import { HrModule } from './hr/hr.module';
import { SecurityModule } from './security/security.module';
import { ReportsModule } from './reports/reports.module';
import { AgentBridgeModule } from './agent-bridge/agent-bridge.module';
import { ExtensionsModule } from './extensions/extensions.module';
import { ControlPlaneModule } from './control-plane/control-plane.module';
import { PortalModule } from './portal/portal.module';
import { ToursModule } from './tours/tours.module';
import { ClinicalIntelModule } from './clinical-intel/clinical-intel.module';

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
    UploadModule,
    MedicalModule,
    LtcModule,
    InventoryModule,
    HrModule,
    SecurityModule,
    ReportsModule,
    AgentBridgeModule,
    ExtensionsModule,
    ControlPlaneModule,
    PortalModule,
    ToursModule,
    ClinicalIntelModule,
  ],
})
export class AppModule {}
