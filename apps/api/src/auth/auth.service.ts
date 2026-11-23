import { Injectable, UnauthorizedException } from '@nestjs/common';
import { JwtService } from '@nestjs/jwt';
import * as bcrypt from 'bcryptjs';
import { PrismaService } from '../prisma/prisma.service';

@Injectable()
export class AuthService {
  constructor(
    private prisma: PrismaService,
    private jwt: JwtService,
  ) {}

  async login(username: string, password: string) {
    const user = await this.prisma.employee.findFirst({
      where: { username, active: true },
    });
    if (!user || !(await bcrypt.compare(password, user.passwordHash))) {
      throw new UnauthorizedException('用户名或密码错误');
    }
    const payload = {
      sub: user.id,
      tenantId: user.tenantId,
      role: user.role,
      username: user.username,
      name: user.name,
    };
    return {
      accessToken: await this.jwt.signAsync(payload),
      user: {
        id: user.id,
        username: user.username,
        name: user.name,
        role: user.role,
        tenantId: user.tenantId,
        phone: user.phone,
      },
    };
  }

  async me(userId: string) {
    const user = await this.prisma.employee.findUnique({ where: { id: userId } });
    if (!user) throw new UnauthorizedException();
    const bindings =
      user.role === 'family'
        ? await this.prisma.familyBinding.findMany({
            where: { employeeId: user.id },
            include: { elder: { select: { id: true, name: true, careLevel: true, status: true } } },
          })
        : [];
    return {
      id: user.id,
      username: user.username,
      name: user.name,
      role: user.role,
      tenantId: user.tenantId,
      phone: user.phone,
      elders: bindings.map((b) => ({ ...b.elder, relation: b.relation })),
    };
  }

  /** 高权限操作前复核管理员密码，签发短时 elevate token */
  async reauth(userId: string, password: string) {
    const user = await this.prisma.employee.findUnique({ where: { id: userId } });
    if (!user || !(await bcrypt.compare(password, user.passwordHash))) {
      throw new UnauthorizedException('管理员密码错误');
    }
    if (user.role !== 'admin') {
      throw new UnauthorizedException('仅管理员可提升权限');
    }
    const elevateToken = await this.jwt.signAsync(
      {
        sub: user.id,
        tenantId: user.tenantId,
        role: user.role,
        username: user.username,
        elevate: true,
        purpose: 'privileged_confirm',
      },
      { expiresIn: '120s' },
    );
    return {
      ok: true,
      elevateToken,
      expiresInSec: 120,
      user: { id: user.id, username: user.username, role: user.role },
    };
  }

  async verifyElevate(elevateToken: string, userId: string) {
    try {
      const payload = await this.jwt.verifyAsync(elevateToken);
      if (!payload?.elevate || payload.sub !== userId || payload.purpose !== 'privileged_confirm') {
        throw new UnauthorizedException('提升令牌无效');
      }
      return payload;
    } catch {
      throw new UnauthorizedException('提升令牌无效或已过期，请重新输入密码');
    }
  }
}
