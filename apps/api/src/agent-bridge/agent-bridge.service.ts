import { Injectable } from '@nestjs/common';

@Injectable()
export class AgentBridgeService {
  private base = process.env.AGENT_BASE_URL || 'http://127.0.0.1:8100';

  async proxy(path: string, init?: RequestInit) {
    const res = await fetch(`${this.base}${path}`, {
      ...init,
      headers: {
        'Content-Type': 'application/json',
        ...(init?.headers || {}),
      },
    });
    const text = await res.text();
    try {
      return { status: res.status, data: JSON.parse(text) };
    } catch {
      return { status: res.status, data: text };
    }
  }

  manifest() {
    return this.proxy('/v1/manifest');
  }

  audit() {
    return this.proxy('/v1/audit?limit=40');
  }

  reviews() {
    return this.proxy('/v1/reviews');
  }

  post(path: string, body: any) {
    return this.proxy(path, { method: 'POST', body: JSON.stringify(body) });
  }
}
