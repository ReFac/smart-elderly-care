import { Injectable, NotFoundException, OnModuleInit } from '@nestjs/common';
import { FEATURE_REGISTRY } from '@nh/shared';
import { PrismaService } from '../prisma/prisma.service';

const DEFAULT_VARS: Array<{ key: string; value: string; valueType: string; groupName: string; description: string }> = [
  { key: 'app.name', value: '智能养老主控台', valueType: 'string', groupName: 'brand', description: '产品名称' },
  { key: 'agent.base_url', value: 'http://127.0.0.1:8100', valueType: 'string', groupName: 'agent', description: 'Agent Runtime 地址' },
  { key: 'family.bill_transparency', value: 'true', valueType: 'boolean', groupName: 'family', description: '家属端账单透明' },
  { key: 'family.meal_visibility', value: 'true', valueType: 'boolean', groupName: 'family', description: '家属端可见餐食' },
  { key: 'mobile.wechat_oa_enabled', value: 'true', valueType: 'boolean', groupName: 'mobile', description: '微信公众号适配开关' },
  { key: 'tour.default_fov', value: '75', valueType: 'number', groupName: 'tour', description: '3D 导览默认 FOV' },
  { key: 'learning.noise_on_fp', value: 'true', valueType: 'boolean', groupName: 'learning', description: '误报自动加噪声' },
  { key: 'learning.noise_on_fn', value: 'true', valueType: 'boolean', groupName: 'learning', description: '漏报自动加噪声' },
];

const DEFAULT_SERVICES = [
  { code: 'api', name: 'Nest 业务 API', baseUrl: 'http://localhost:3000/api', healthPath: '/auth/login', enabled: true },
  { code: 'admin', name: '管理主控台', baseUrl: 'http://localhost:5173', healthPath: '/', enabled: true },
  { code: 'family', name: '用户/家属 H5', baseUrl: 'http://localhost:5174', healthPath: '/', enabled: true },
  { code: 'agent', name: 'Agent Runtime', baseUrl: 'http://127.0.0.1:8100', healthPath: '/health', enabled: true },
];

const DEFAULT_APIS: Array<{ method: string; path: string; module: string; audience: string; description: string }> = [
  ...FEATURE_REGISTRY.map((f) => ({
    method: 'GET',
    path: f.apiPrefix.replace(/^\/api/, '') || '/',
    module: f.id,
    audience: f.group === 'family' ? 'user' : f.group === 'caregiver' ? 'employee' : 'admin',
    description: f.description,
  })),
  { method: 'GET', path: '/portal/user/home', module: 'portal', audience: 'user', description: '用户端首页聚合' },
  { method: 'GET', path: '/portal/employee/home', module: 'portal', audience: 'employee', description: '员工端首页聚合' },
  { method: 'GET', path: '/tours/public', module: 'tours', audience: 'user', description: '公开 3D 房态导览列表' },
  { method: 'GET', path: '/control/variables', module: 'control-plane', audience: 'admin', description: '运行变量列表' },
];

@Injectable()
export class ControlPlaneService implements OnModuleInit {
  constructor(private prisma: PrismaService) {}

  async onModuleInit() {
    const tenant = await this.prisma.tenant.findFirst();
    if (!tenant) return;
    await this.ensureDefaults(tenant.id);
  }

  async ensureDefaults(tenantId: string) {
    for (const v of DEFAULT_VARS) {
      await this.prisma.systemVariable.upsert({
        where: { tenantId_key: { tenantId, key: v.key } },
        create: { tenantId, ...v },
        update: {},
      });
    }
    for (const s of DEFAULT_SERVICES) {
      await this.prisma.serviceRegistry.upsert({
        where: { tenantId_code: { tenantId, code: s.code } },
        create: {
          tenantId,
          code: s.code,
          name: s.name,
          baseUrl: s.baseUrl,
          healthPath: s.healthPath,
          enabled: s.enabled,
          status: 'unknown',
        },
        update: {},
      });
    }
    for (const a of DEFAULT_APIS) {
      await this.prisma.apiEndpointMeta.upsert({
        where: { tenantId_method_path: { tenantId, method: a.method, path: a.path } },
        create: { tenantId, ...a, enabled: true },
        update: {},
      });
    }
  }

  listVariables(tenantId: string, group?: string) {
    return this.prisma.systemVariable.findMany({
      where: { tenantId, ...(group ? { groupName: group } : {}) },
      orderBy: [{ groupName: 'asc' }, { key: 'asc' }],
    });
  }

  async upsertVariable(tenantId: string, data: any) {
    return this.prisma.systemVariable.upsert({
      where: { tenantId_key: { tenantId, key: data.key } },
      create: {
        tenantId,
        key: data.key,
        value: String(data.value ?? ''),
        valueType: data.valueType || 'string',
        groupName: data.groupName || 'general',
        description: data.description,
        editable: data.editable !== false,
      },
      update: {
        value: String(data.value ?? ''),
        valueType: data.valueType,
        groupName: data.groupName,
        description: data.description,
        editable: data.editable,
      },
    });
  }

  async deleteVariable(tenantId: string, key: string) {
    const row = await this.prisma.systemVariable.findFirst({ where: { tenantId, key } });
    if (!row) throw new NotFoundException();
    return this.prisma.systemVariable.delete({ where: { id: row.id } });
  }

  listServices(tenantId: string) {
    return this.prisma.serviceRegistry.findMany({ where: { tenantId }, orderBy: { code: 'asc' } });
  }

  async upsertService(tenantId: string, data: any) {
    return this.prisma.serviceRegistry.upsert({
      where: { tenantId_code: { tenantId, code: data.code } },
      create: {
        tenantId,
        code: data.code,
        name: data.name,
        baseUrl: data.baseUrl,
        healthPath: data.healthPath,
        enabled: data.enabled !== false,
        status: data.status || 'unknown',
        metaJson: data.metaJson,
      },
      update: {
        name: data.name,
        baseUrl: data.baseUrl,
        healthPath: data.healthPath,
        enabled: data.enabled,
        status: data.status,
        metaJson: data.metaJson,
      },
    });
  }

  async probeService(tenantId: string, code: string) {
    const svc = await this.prisma.serviceRegistry.findFirst({ where: { tenantId, code } });
    if (!svc) throw new NotFoundException();
    if (!svc.baseUrl) {
      return this.prisma.serviceRegistry.update({ where: { id: svc.id }, data: { status: 'unknown' } });
    }
    const url = `${svc.baseUrl.replace(/\/$/, '')}${svc.healthPath || ''}`;
    let status = 'down';
    try {
      const res = await fetch(url, { method: 'GET' });
      status = res.status < 500 ? 'up' : 'down';
    } catch {
      status = 'down';
    }
    return this.prisma.serviceRegistry.update({ where: { id: svc.id }, data: { status } });
  }

  listApis(tenantId: string, audience?: string) {
    return this.prisma.apiEndpointMeta.findMany({
      where: { tenantId, ...(audience ? { audience } : {}) },
      orderBy: [{ module: 'asc' }, { path: 'asc' }],
    });
  }

  async upsertApi(tenantId: string, data: any) {
    return this.prisma.apiEndpointMeta.upsert({
      where: {
        tenantId_method_path: { tenantId, method: data.method, path: data.path },
      },
      create: {
        tenantId,
        method: data.method,
        path: data.path,
        module: data.module || 'custom',
        audience: data.audience || 'admin',
        enabled: data.enabled !== false,
        description: data.description,
        version: data.version || 'v1',
      },
      update: {
        module: data.module,
        audience: data.audience,
        enabled: data.enabled,
        description: data.description,
        version: data.version,
      },
    });
  }

  /** 聚合快照：便于主管理员一屏掌控 */
  async snapshot(tenantId: string) {
    const [variables, services, apis] = await Promise.all([
      this.listVariables(tenantId),
      this.listServices(tenantId),
      this.listApis(tenantId),
    ]);
    return {
      variables,
      services,
      apis,
      counts: {
        variables: variables.length,
        services: services.length,
        apis: apis.length,
        apisEnabled: apis.filter((a) => a.enabled).length,
      },
    };
  }
}
