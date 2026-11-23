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
  await prisma.medicationDose.deleteMany();
  await prisma.medicationPlan.deleteMany();
  await prisma.drugStockLog.deleteMany();
  await prisma.adverseReaction.deleteMany();
  await prisma.vitalSign.deleteMany();
  await prisma.healthExam.deleteMany();
  await prisma.chronicFollowUp.deleteMany();
  await prisma.medicalOrder.deleteMany();
  await prisma.referralRecord.deleteMany();
  await prisma.ltcServiceRecord.deleteMany();
  await prisma.ltcReconciliation.deleteMany();
  await prisma.ltcAssessment.deleteMany();
  await prisma.ltcServiceItem.deleteMany();
  await prisma.drug.deleteMany();
  await prisma.inventoryStockLog.deleteMany();
  await prisma.maintenanceOrder.deleteMany();
  await prisma.attendance.deleteMany();
  await prisma.performanceRecord.deleteMany();
  await prisma.accessLog.deleteMany();
  await prisma.reportSubmission.deleteMany();
  await prisma.roomTourHotspot.deleteMany();
  await prisma.roomTour.deleteMany();
  await prisma.clinicalPush.deleteMany();
  await prisma.prediagnosisReport.deleteMany();
  await prisma.clinicalFinding.deleteMany();
  await prisma.acousticEvent.deleteMany();
  await prisma.acousticDevice.deleteMany();
  await prisma.promptTemplate.deleteMany();
  await prisma.acousticSensitivityConfig.deleteMany();
  await prisma.apiEndpointMeta.deleteMany();
  await prisma.serviceRegistry.deleteMany();
  await prisma.systemVariable.deleteMany();
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
        enabled: true,
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

  // ---- Medical / LTC / Inventory / HR / Security / Reports samples ----
  const drug = await prisma.drug.create({
    data: {
      tenantId: tenant.id,
      name: '氨氯地平',
      spec: '5mg*28片',
      quantity: 40,
      isHighRisk: false,
      expireAt: new Date(Date.now() + 180 * 86400000),
    },
  });
  await prisma.drug.create({
    data: {
      tenantId: tenant.id,
      name: '胰岛素注射液',
      spec: '300IU',
      quantity: 8,
      isHighRisk: true,
      lowStock: 5,
      expireAt: new Date(Date.now() + 90 * 86400000),
    },
  });
  await prisma.vitalSign.create({
    data: {
      elderId: elders[0].id,
      systolic: 138,
      diastolic: 86,
      glucose: 6.2,
      temperature: 36.6,
      spo2: 97,
      pulse: 72,
    },
  });
  const medPlan = await prisma.medicationPlan.create({
    data: {
      elderId: elders[0].id,
      drugId: drug.id,
      dosage: '1片',
      schedule: '每日一次',
      startDate: new Date(),
      active: true,
    },
  });
  await prisma.medicationDose.create({
    data: { planId: medPlan.id, scheduledAt: new Date(), status: 'pending' },
  });
  await prisma.healthExam.create({
    data: {
      elderId: elders[0].id,
      examDate: new Date(),
      examType: 'regular',
      summary: '血压偏高，其余大致正常',
      nextDueAt: new Date(Date.now() + 90 * 86400000),
    },
  });
  await prisma.chronicFollowUp.create({
    data: {
      elderId: elders[0].id,
      disease: '高血压',
      followDate: new Date(),
      result: '规律服药，血压可控',
    },
  });
  await prisma.medicalOrder.create({
    data: {
      elderId: elders[0].id,
      source: 'clinic',
      content: '监测血压 BID，低盐饮食',
      doctorName: '王医生',
    },
  });

  for (const item of [
    { code: 'LTC-FEED', name: '协助进食', unitPrice: 40 },
    { code: 'LTC-TURN', name: '翻身叩背', unitPrice: 35 },
    { code: 'LTC-BATH', name: '协助沐浴', unitPrice: 60 },
  ]) {
    await prisma.ltcServiceItem.create({ data: { tenantId: tenant.id, ...item } });
  }
  await prisma.ltcAssessment.create({
    data: {
      elderId: elders[1].id,
      level: 'L2',
      assessDate: new Date(),
      assessor: '评估员周某',
      resultSummary: '中度失能，符合长护险待遇',
      status: 'submitted',
    },
  });
  await prisma.ltcServiceRecord.create({
    data: {
      elderId: elders[1].id,
      itemCode: 'LTC-FEED',
      itemName: '协助进食',
      quantity: 1,
      amount: 40,
      caregiver: '王护理',
    },
  });
  await prisma.ltcReconciliation.create({
    data: {
      elderId: elders[1].id,
      period: new Date().toISOString().slice(0, 7),
      claimAmount: 1200,
      approvedAmount: 0,
      status: 'pending',
    },
  });

  await prisma.inventoryItem.createMany({
    data: [
      { tenantId: tenant.id, name: '成人纸尿裤', sku: 'DP-L', category: 'diaper', quantity: 120, unit: '包', lowStock: 30 },
      { tenantId: tenant.id, name: '一次性手套', sku: 'GL-M', category: 'consumable', quantity: 8, unit: '盒', lowStock: 10 },
      { tenantId: tenant.id, name: '护理垫', sku: 'PD-01', category: 'care', quantity: 50, unit: '包', lowStock: 15 },
    ],
  });
  await prisma.maintenanceOrder.create({
    data: {
      tenantId: tenant.id,
      title: 'A栋201卫生间漏水',
      location: 'A201',
      description: '地漏堵塞',
      status: 'pending',
    },
  });

  await prisma.shift.create({
    data: {
      tenantId: tenant.id,
      employeeId: caregiver.id,
      shiftDate: new Date(),
      shiftType: 'day',
    },
  });
  await prisma.attendance.create({
    data: { employeeId: caregiver.id, checkInAt: new Date(), note: '正常到岗' },
  });

  await prisma.alert.create({
    data: {
      tenantId: tenant.id,
      type: 'sos',
      title: '床头SOS测试告警',
      message: '硬件对接预留演示',
      elderId: elders[2].id,
      source: 'hardware',
      severity: 'high',
      status: 'open',
    },
  });
  await prisma.accessLog.create({
    data: {
      tenantId: tenant.id,
      person: '张家属',
      direction: 'in',
      gate: '正门',
      relatedElderId: elders[0].id,
    },
  });

  await prisma.reportSubmission.create({
    data: {
      tenantId: tenant.id,
      reportType: 'civil_monthly',
      period: new Date().toISOString().slice(0, 7),
      status: 'draft',
      payloadJson: JSON.stringify({ note: '可由报表页一键重新生成' }),
    },
  });

  await prisma.roomTour.create({
    data: {
      tenantId: tenant.id,
      title: 'A栋标准间全景',
      sceneType: 'panorama',
      sceneUrl: 'https://images.unsplash.com/photo-1582719478250-c89cae4dc85b?w=1600',
      coverUrl: 'https://images.unsplash.com/photo-1582719478250-c89cae4dc85b?w=400',
      published: true,
      fov: 75,
      hotspots: {
        create: [
          { label: '床位区', kind: 'info', yaw: -15, pitch: -5, payloadJson: JSON.stringify({ note: '双人护理床' }) },
          { label: '卫生间', kind: 'info', yaw: 40, pitch: 0 },
          { label: '门口', kind: 'link', yaw: -50, pitch: 5 },
        ],
      },
    },
  });
  await prisma.roomTour.create({
    data: {
      tenantId: tenant.id,
      title: '公共活动区',
      sceneType: 'panorama',
      sceneUrl: 'https://images.unsplash.com/photo-1631889993959-41b4e9c6e3c5?w=1600',
      published: true,
      hotspots: {
        create: [{ label: '休息沙发', kind: 'info', yaw: 10, pitch: -8 }],
      },
    },
  });

  await prisma.acousticDevice.create({
    data: {
      tenantId: tenant.id,
      code: 'mic-a201',
      name: 'A201 床头麦克风',
      bedId: elders[0].bedId || undefined,
      elderId: elders[0].id,
      vendor: 'generic',
      enabled: true,
    },
  });
  await prisma.acousticSensitivityConfig.create({
    data: { tenantId: tenant.id, name: 'default', modelId: 'stub-acoustic-v0' },
  });
  const { BUILTIN_PROMPTS } = await import('../src/clinical-intel/prompts');
  for (const p of BUILTIN_PROMPTS) {
    await prisma.promptTemplate.create({
      data: {
        tenantId: tenant.id,
        key: p.key,
        title: p.title,
        version: p.version,
        content: p.content,
      },
    });
  }

  console.log('Seed complete');
  console.log(`Beds: ${allBeds.length}`);
  console.log('Accounts (password 123456): admin / nurse / caregiver / finance / family');
  console.log(`Family bound to elder: ${elders[0].name}`);
  console.log('Domains seeded: medical/ltc/inventory/hr/security/reports/control/tours/clinical-intel');
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
