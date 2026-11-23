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
}
