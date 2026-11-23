import { PrismaClient } from '@prisma/client';
import * as bcrypt from 'bcryptjs';
import { CARE_TASK_TEMPLATES, FeatureFlagKey } from '@nh/shared';

const prisma = new PrismaClient();

async function main() {
  await prisma.payment.deleteMany();
  await prisma.billLine.deleteMany();
  await prisma.bill.deleteMany();
  await prisma.careCheckin.deleteMany();
  await prisma.careTask.deleteMany();
  await prisma.carePlan.deleteMany();
  await prisma.serviceOrder.deleteMany();
  await prisma.visitRecord.deleteMany();
  await prisma.emotionRecord.deleteMany();
  await prisma.contract.deleteMany();
  await prisma.bedChangeLog.deleteMany();
  await prisma.familyBinding.deleteMany();
  await prisma.elderContact.deleteMany();
  await prisma.elderHealth.deleteMany();
  await prisma.mealRestriction.deleteMany();
  await prisma.deposit.deleteMany();
  await prisma.waiver.deleteMany();
  await prisma.attachment.deleteMany();
  await prisma.deviceLocation.deleteMany();
  await prisma.elder.deleteMany();
  await prisma.bed.deleteMany();
  await prisma.room.deleteMany();
  await prisma.floor.deleteMany();
  await prisma.building.deleteMany();
  await prisma.employee.deleteMany();
  await prisma.feeItem.deleteMany();
  await prisma.priceRule.deleteMany();
  await prisma.mealMenu.deleteMany();
  await prisma.featureFlag.deleteMany();
  await prisma.systemAiConfig.deleteMany();
  await prisma.alert.deleteMany();
  await prisma.inventoryItem.deleteMany();
  await prisma.shift.deleteMany();
  await prisma.tenant.deleteMany();

  const tenant = await prisma.tenant.create({
    data: { name: '阳光养老示范院', code: 'demo' },
  });

  const passwordHash = await bcrypt.hash('123456', 10);
  const [admin, nurse, caregiver, finance, family] = await Promise.all([
    prisma.employee.create({
      data: {
        tenantId: tenant.id,
        username: 'admin',
        passwordHash,
        name: '系统管理员',
        role: 'admin',
        phone: '13800000001',
      },
    }),
    prisma.employee.create({
      data: {
        tenantId: tenant.id,
        username: 'nurse',
        passwordHash,
        name: '李护士',
        role: 'nurse',
        phone: '13800000002',
      },
    }),
    prisma.employee.create({
      data: {
        tenantId: tenant.id,
        username: 'caregiver',
        passwordHash,
        name: '王护理',
        role: 'caregiver',
        phone: '13800000003',
      },
    }),
    prisma.employee.create({
      data: {
        tenantId: tenant.id,
        username: 'finance',
        passwordHash,
        name: '赵财务',
        role: 'finance',
        phone: '13800000004',
      },
    }),
    prisma.employee.create({
      data: {
        tenantId: tenant.id,
        username: 'family',
        passwordHash,
        name: '张家属',
        role: 'family',
        phone: '13800000005',
      },
    }),
  ]);

  for (const key of Object.values(FeatureFlagKey)) {
    await prisma.featureFlag.create({
      data: {
        tenantId: tenant.id,
        key,
        enabled: key === FeatureFlagKey.OCR_LLM,
      },
    });
  }

  await prisma.systemAiConfig.create({
    data: {
      tenantId: tenant.id,
      provider: 'openai_compatible',
      baseUrl: 'https://api.deepseek.com/v1',
      apiKey: '',
      model: 'deepseek-chat',
      ocrProvider: 'mock',
    },
  });

  const feeDefs = [
    { code: 'bed', name: '床位费', category: 'bed', defaultPrice: 2000 },
    { code: 'care', name: '护理费', category: 'care', defaultPrice: 1500 },
    { code: 'meal', name: '伙食费', category: 'meal', defaultPrice: 900 },
    { code: 'consumable', name: '耗材费', category: 'other', defaultPrice: 200 },
  ];
  for (const f of feeDefs) {
    await prisma.feeItem.create({ data: { tenantId: tenant.id, unit: '月', ...f } });
  }

  const carePrices: Record<string, number> = {
    independent: 800,
    semi_disabled: 1500,
    disabled: 2500,
    dementia: 2800,
  };
  for (const [careLevel, price] of Object.entries(carePrices)) {
    await prisma.priceRule.create({
      data: {
        tenantId: tenant.id,
        careLevel,
        feeItemCode: 'care',
        price,
        billingCycle: 'monthly',
      },
    });
    await prisma.priceRule.create({
      data: {
        tenantId: tenant.id,
        careLevel,
        feeItemCode: 'bed',
        price: 2000,
        billingCycle: 'monthly',
      },
    });
    await prisma.priceRule.create({
      data: {
        tenantId: tenant.id,
        careLevel,
        feeItemCode: 'meal',
        price: 900,
        billingCycle: 'monthly',
      },
    });
  }

  // Building A: 5 floors × 12 rooms × 2 beds = 120
  // Building B: 4 floors × 12 rooms × 2 beds = 96
  // Total 216 beds
  const buildings = [
    { name: 'A栋颐养楼', code: 'A', floors: 5 },
    { name: 'B栋护理楼', code: 'B', floors: 4 },
  ];

  const allBeds: { id: string; code: string }[] = [];

  for (const b of buildings) {
    const building = await prisma.building.create({
      data: {
        tenantId: tenant.id,
        name: b.name,
        code: b.code,
        address: '示范市幸福路 88 号',
      },
    });
    for (let level = 1; level <= b.floors; level++) {
      const floor = await prisma.floor.create({
        data: {
          buildingId: building.id,
          name: `${level}F`,
          level,
        },
      });
      for (let r = 1; r <= 12; r++) {
        const roomNumber = `${b.code}${level}${String(r).padStart(2, '0')}`;
        const room = await prisma.room.create({
          data: { floorId: floor.id, number: roomNumber, capacity: 2 },
        });
        for (const bedCode of ['1', '2']) {
          const bed = await prisma.bed.create({
            data: {
              roomId: room.id,
              code: `${roomNumber}-${bedCode}`,
              status: 'idle',
            },
          });
          allBeds.push({ id: bed.id, code: bed.code });
        }
      }
    }
  }

  const elderSeeds = [
    {
      name: '张建国',
      gender: '男',
      careLevel: 'semi_disabled',
      paymentType: 'self',
      wanderRisk: false,
      allergies: '青霉素',
      chronicDiseases: '高血压',
    },
    {
      name: '李秀英',
      gender: '女',
      careLevel: 'disabled',
      paymentType: 'long_term_care',
      wanderRisk: false,
      allergies: '',
      chronicDiseases: '糖尿病',
    },
    {
      name: '王德福',
      gender: '男',
      careLevel: 'dementia',
      paymentType: 'medical',
      wanderRisk: true,
      allergies: '海鲜',
      chronicDiseases: '阿尔茨海默',
    },
    {
      name: '赵桂兰',
      gender: '女',
      careLevel: 'independent',
      paymentType: 'self',
      wanderRisk: false,
      allergies: '',
      chronicDiseases: '',
    },
    {
      name: '陈志强',
      gender: '男',
      careLevel: 'semi_disabled',
      paymentType: 'self',
      wanderRisk: false,
      allergies: '磺胺',
      chronicDiseases: '冠心病',
    },
  ];

  const elders: any[] = [];
  for (let i = 0; i < elderSeeds.length; i++) {
    const s = elderSeeds[i];
    const bed = allBeds[i];
    const elder = await prisma.elder.create({
      data: {
        tenantId: tenant.id,
        name: s.name,
        gender: s.gender,
        idNumber: `110101194${i}0101${1000 + i}`,
        paymentType: s.paymentType,
        careLevel: s.careLevel,
        admitSource: '社区转介',
        checkInDate: new Date(),
        depositAmount: 5000,
        wanderRisk: s.wanderRisk,
        bedId: bed.id,
        status: 'active',
        health: {
          create: {
            allergies: s.allergies,
            chronicDiseases: s.chronicDiseases,
            dietTaboos: s.allergies ? '忌海鲜' : '普食',
            assessmentNote: '民政评估已完成',
          },
        },
        contacts: {
          create: [
            {
              name: `${s.name[0]}家属`,
              relation: '子女',
              phone: `1390000000${i}`,
              isEmergency: true,
              isPrimary: true,
            },
          ],
        },
        contracts: {
          create: [
            {
              type: 'admit',
              title: '入住协议',
              startDate: new Date(),
              endDate: new Date(Date.now() + 365 * 24 * 3600 * 1000),
            },
          ],
        },
      },
    });
    await prisma.bed.update({ where: { id: bed.id }, data: { status: 'occupied' } });
    await prisma.bedChangeLog.create({
      data: { elderId: elder.id, toBedId: bed.id, reason: '入住分床', operatedBy: '系统管理员' },
    });
    await prisma.deposit.create({
      data: { elderId: elder.id, amount: 5000, type: 'in', remark: '入住押金' },
    });
    const items =
      CARE_TASK_TEMPLATES[s.careLevel as keyof typeof CARE_TASK_TEMPLATES] ||
      CARE_TASK_TEMPLATES.independent;
    const plan = await prisma.carePlan.create({
      data: {
        elderId: elder.id,
        careLevel: s.careLevel,
        itemsJson: JSON.stringify(items),
        active: true,
      },
    });
    const morning = new Date();
    morning.setHours(9, 0, 0, 0);
    for (let t = 0; t < items.length; t++) {
      const scheduledAt = new Date(morning);
      scheduledAt.setHours(9 + t);
      await prisma.careTask.create({
        data: {
          elderId: elder.id,
          carePlanId: plan.id,
          title: items[t],
          scheduledAt,
          status: 'pending',
        },
      });
    }
    elders.push(elder);
  }

  await prisma.familyBinding.create({
    data: { employeeId: family.id, elderId: elders[0].id, relation: '儿子' },
  });

  // Sample bill for first elder
  const now = new Date();
  const periodStart = new Date(now.getFullYear(), now.getMonth(), 1);
  const periodEnd = new Date(now.getFullYear(), now.getMonth() + 1, 0, 23, 59, 59);
  await prisma.bill.create({
    data: {
      elderId: elders[0].id,
      periodStart,
      periodEnd,
      totalAmount: 4400,
      paidAmount: 0,
      status: 'unpaid',
      lines: {
        create: [
          { feeCode: 'bed', feeName: '床位费', quantity: 1, unitPrice: 2000, amount: 2000 },
          { feeCode: 'care', feeName: '护理费', quantity: 1, unitPrice: 1500, amount: 1500 },
          { feeCode: 'meal', feeName: '伙食费', quantity: 1, unitPrice: 900, amount: 900 },
        ],
      },
    },
  });

  const mealTypes = [
    { mealType: 'breakfast', dishes: '小米粥,鸡蛋,馒头,咸菜' },
    { mealType: 'lunch', dishes: '米饭,清蒸鱼,番茄炒蛋,时蔬' },
    { mealType: 'dinner', dishes: '面条,青菜豆腐,水果' },
  ];
  for (let d = 0; d < 7; d++) {
    const date = new Date();
    date.setHours(12, 0, 0, 0);
    date.setDate(date.getDate() + d);
    for (const m of mealTypes) {
      await prisma.mealMenu.create({
        data: {
          tenantId: tenant.id,
          date,
          mealType: m.mealType,
          dishes: m.dishes,
          dietTags: '普食,软食可选',
        },
      });
    }
  }

  console.log('Seed complete');
  console.log(`Beds: ${allBeds.length}`);
  console.log('Accounts (password 123456): admin / nurse / caregiver / finance / family');
  console.log(`Family bound to elder: ${elders[0].name}`);
  void nurse;
  void caregiver;
  void finance;
  void admin;
}

main()
  .catch((e) => {
    console.error(e);
    process.exit(1);
  })
  .finally(async () => {
    await prisma.$disconnect();
  });
